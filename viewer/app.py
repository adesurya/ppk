"""
TikTok multi-live backend (starter).

Run:
    pip install fastapi uvicorn httpx yt-dlp
    uvicorn app:app --host 0.0.0.0 --port 8800

Endpoints:
    GET /api/resolve?user=<username>   -> { play_url } (proxied .m3u8)
    GET /api/proxy?url=<encoded_url>    -> playlist/segment via proxy (fixes CORS + expiry hop)

Catatan:
- yt-dlp dipakai sebagai extractor paling tahan banting. Pastikan versinya terbaru:
      pip install -U yt-dlp
- URL stream TikTok ada masa kedaluwarsa (query `expire=`). Frontend sebaiknya
  re-resolve kalau playback berhenti.
- Proxy ini minimal (cukup untuk monitoring internal). Untuk skala besar,
  stream segmen (StreamingResponse) dan tambahkan cache.
"""
import subprocess
import urllib.parse
import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="tiktok-multi-live")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # batasi ke domain frontend kamu di produksi
    allow_methods=["*"],
    allow_headers=["*"],
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://www.tiktok.com/"}


def resolve_m3u8(user: str) -> str:
    """Kembalikan URL .m3u8 (atau FLV) langsung dari TikTok live via yt-dlp."""
    user = user.lstrip("@")
    live_url = f"https://www.tiktok.com/@{user}/live"
    try:
        out = subprocess.run(
            ["yt-dlp", "-g", "--no-warnings", live_url],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "yt-dlp timeout")
    urls = [l.strip() for l in out.stdout.splitlines() if l.startswith("http")]
    if not urls:
        # biasanya: tidak sedang live, atau diblokir anti-bot
        raise HTTPException(404, f"no stream for @{user} ({out.stderr.strip()[:200]})")
    return urls[0]


@app.get("/api/resolve")
def api_resolve(user: str):
    raw = resolve_m3u8(user)
    proxied = "/api/proxy?url=" + urllib.parse.quote(raw, safe="")
    return {"user": user.lstrip("@"), "raw_url": raw, "play_url": proxied}


@app.get("/api/proxy")
async def proxy(url: str):
    async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as c:
        r = await c.get(url)
    ct = r.headers.get("content-type", "")
    is_playlist = url.split("?")[0].endswith(".m3u8") or "mpegurl" in ct

    if not is_playlist:
        # segmen .ts/.m4s/.aac atau key -> teruskan apa adanya
        return Response(content=r.content, media_type=ct or "video/mp2t")

    # rewrite playlist agar semua URL lewat proxy ini
    base = url.rsplit("/", 1)[0] + "/"
    lines = []
    for line in r.text.splitlines():
        s = line.strip()
        if s.startswith("#EXT-X-KEY") and 'URI="' in s:
            pre, rest = s.split('URI="', 1)
            key_url, post = rest.split('"', 1)
            abs_key = key_url if key_url.startswith("http") else urllib.parse.urljoin(base, key_url)
            lines.append(f'{pre}URI="/api/proxy?url={urllib.parse.quote(abs_key, safe="")}"{post}')
        elif s and not s.startswith("#"):
            abs_url = s if s.startswith("http") else urllib.parse.urljoin(base, s)
            lines.append("/api/proxy?url=" + urllib.parse.quote(abs_url, safe=""))
        else:
            lines.append(line)
    return PlainTextResponse("\n".join(lines), media_type="application/vnd.apple.mpegurl")
