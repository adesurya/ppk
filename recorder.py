#!/usr/bin/env python3
"""
TikTok Multi-Account Live Recorder
==================================

Pantau banyak akun TikTok sekaligus. Begitu sebuah akun LIVE, langsung direkam
ke drive lokal (tanpa re-encode). Saat live berakhir / putus, recorder menunggu
dan otomatis merekam lagi sesi berikutnya.

Fitur:
- Multi-account konkuren (1 task asyncio per akun).
- Auto-detect live (polling) + auto-resume.
- ffmpeg -c copy (cepat, kualitas asli). Fragmented MP4 -> file tetap valid
  walau proses di-kill / stream putus.
- File tersimpan: <out>/<username>/<username>_<YYYYmmdd_HHMMSS>.mp4
- Shutdown rapi (Ctrl+C): semua ffmpeg di-finalize dulu sebelum keluar.
- Tidak ada silent failure: ffmpeg & yt-dlp dicek di awal, error di-log.

Prasyarat:
    pip install -U yt-dlp
    # ffmpeg harus ada di PATH (apt install ffmpeg / yum install ffmpeg)

Pakai:
    # langsung sebut username (tanpa @)
    python recorder.py user1 user2 user3

    # atau dari file (satu username per baris, '#' = komentar)
    python recorder.py --file accounts.txt --out /data/recordings --poll 30

Opsi:
    --out   DIR   folder output (default: ./recordings)
    --poll  SEC   interval cek live saat akun sedang offline (default: 30)
    --file  PATH  file daftar akun
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import signal
import sys
from datetime import datetime
from pathlib import Path

import logging

YTDLP = "yt-dlp"
FFMPEG = "ffmpeg"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rec")


async def wait_or_shutdown(seconds: float, shutdown: asyncio.Event):
    """Tidur `seconds`, tapi langsung bangun kalau shutdown dipicu."""
    try:
        await asyncio.wait_for(shutdown.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def resolve(user: str) -> list[str]:
    """Kembalikan SEMUA URL stream kalau akun live (TikTok kadang memisah
    video & audio -> yt-dlp -g bisa balik >1 URL), else list kosong."""
    proc = await asyncio.create_subprocess_exec(
        YTDLP, "-g", "--no-warnings", f"https://www.tiktok.com/@{user}/live",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=40)
    except asyncio.TimeoutError:
        proc.kill()
        log.warning(f"[{user}] resolve timeout")
        return []
    urls = [l.strip() for l in out.decode(errors="ignore").splitlines()
            if l.startswith("http")]
    if urls:
        return urls
    msg = err.decode(errors="ignore").strip().splitlines()
    if msg:
        log.debug(f"[{user}] not live: {msg[-1][:120]}")
    return []


async def record_once(user: str, urls: list[str], out_dir: Path,
                      shutdown: asyncio.Event) -> int:
    """Rekam satu sesi sampai stream berakhir / putus / shutdown.
    Mendukung >1 URL input (video & audio terpisah) lalu digabung."""
    udir = out_dir / user
    udir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = udir / f"{user}_{ts}.mp4"

    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning"]
    # opsi input diulang sebelum SETIAP -i (berlaku per-input)
    for u in urls:
        cmd += [
            "-fflags", "+genpts",            # bangun ulang timestamp -> sinkron A/V
            "-user_agent", UA,
            "-headers", "Referer: https://www.tiktok.com/\r\n",
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", u,
        ]
    # ambil video & audio dari tiap input ('?' = abaikan kalau tidak ada),
    # supaya muxed (1 URL) maupun split (video+audio terpisah) sama-sama jalan
    for i in range(len(urls)):
        cmd += ["-map", f"{i}:v:0?", "-map", f"{i}:a:0?"]
    cmd += [
        "-c:v", "copy",
        # audio di-RE-ENCODE (ringan): track jadi bersih & playable di semua
        # player (QuickTime sering bisu kalau audio HLS hanya di-copy).
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        # fragmented mp4 -> file valid walau ffmpeg di-kill:
        "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", str(outfile),
    ]

    log.info(f"[{user}] ▶ REC ({len(urls)} input) -> {outfile.name}")
    proc = await asyncio.create_subprocess_exec(*cmd)

    stop_task = asyncio.ensure_future(shutdown.wait())
    wait_task = asyncio.ensure_future(proc.wait())
    done, _ = await asyncio.wait({stop_task, wait_task},
                                 return_when=asyncio.FIRST_COMPLETED)

    if stop_task in done and proc.returncode is None:
        # shutdown saat masih merekam -> minta ffmpeg finalize via SIGINT
        log.info(f"[{user}] ⏹ stopping, finalizing…")
        try:
            proc.send_signal(signal.SIGINT)
            await asyncio.wait_for(proc.wait(), timeout=15)
        except (ProcessLookupError, asyncio.TimeoutError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    for t in (stop_task, wait_task):
        if not t.done():
            t.cancel()

    rc = proc.returncode
    size = outfile.stat().st_size if outfile.exists() else 0
    if size == 0:
        outfile.unlink(missing_ok=True)
        log.warning(f"[{user}] ⏹ ended rc={rc} (kosong, file dihapus)")
    else:
        log.info(f"[{user}] ⏹ ended rc={rc} | {size/1e6:.1f} MB | {outfile.name}")
    return rc


async def watch(user: str, out_dir: Path, poll: int, shutdown: asyncio.Event):
    """Loop per-akun: cek live -> rekam -> ulangi."""
    log.info(f"[{user}] 👀 watching (poll {poll}s)")
    while not shutdown.is_set():
        urls = await resolve(user)
        if urls:
            await record_once(user, urls, out_dir, shutdown)
            # cek cepat — mungkin masih live (URL kedaluwarsa) atau sudah selesai
            await wait_or_shutdown(5, shutdown)
        else:
            await wait_or_shutdown(poll, shutdown)
    log.info(f"[{user}] watcher stopped")


def load_accounts(args) -> list[str]:
    accounts: list[str] = list(args.accounts)
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip().lstrip("@")
            if line:
                accounts.append(line)
    # dedup, jaga urutan
    seen, out = set(), []
    for a in accounts:
        a = a.lower()
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def preflight():
    missing = [t for t in (YTDLP, FFMPEG) if shutil.which(t) is None]
    if missing:
        log.error("Tidak ditemukan di PATH: " + ", ".join(missing))
        log.error("Install: pip install -U yt-dlp ; dan pasang ffmpeg.")
        sys.exit(1)


async def main_async(accounts: list[str], out_dir: Path, poll: int):
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown.set)
        except NotImplementedError:
            pass  # Windows

    log.info(f"Recording {len(accounts)} akun -> {out_dir.resolve()}")
    log.info("Akun: " + ", ".join(accounts))
    log.info("Ctrl+C untuk berhenti (file akan di-finalize dulu).")

    tasks = [asyncio.create_task(watch(u, out_dir, poll, shutdown))
             for u in accounts]
    await asyncio.gather(*tasks)
    log.info("Selesai. Semua file tersimpan.")


def main():
    ap = argparse.ArgumentParser(description="TikTok multi-account live recorder")
    ap.add_argument("accounts", nargs="*", help="username TikTok (tanpa @)")
    ap.add_argument("--file", help="file daftar akun (1 per baris)")
    ap.add_argument("--out", default="recordings", help="folder output")
    ap.add_argument("--poll", type=int, default=30, help="interval cek live (detik)")
    args = ap.parse_args()

    preflight()
    accounts = load_accounts(args)
    if not accounts:
        ap.error("tidak ada akun. Sebutkan username atau pakai --file.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(main_async(accounts, out_dir, args.poll))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()