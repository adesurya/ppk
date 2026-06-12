# TikTok Live Toolkit

Perekam **TikTok Live** multi-akun ke drive lokal, plus *viewer* web untuk
menonton banyak live sekaligus. Semua khusus TikTok.

Isi paket:

```
tiktok-live-toolkit/
├── recorder.py        # PEREKAM multi-akun -> file .mp4 lokal (utama)
├── accounts.txt       # contoh daftar akun
├── requirements.txt
├── README.md
└── viewer/            # (opsional) nonton banyak live di browser
    ├── app.py         # backend FastAPI (resolve + proxy CORS)
    └── index.html     # grid hls.js
```

> Sudah diverifikasi jalan: yt-dlp me-route URL TikTok ke extractor `tiktok:live`,
> dan engine perekam menghasilkan file MP4 valid (video+audio), termasuk saat
> rekaman dipotong di tengah maupun saat 3 akun direkam bersamaan.

---

## 1. Prasyarat

- **Python 3.10+**
- **ffmpeg** terpasang di PATH
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - CentOS/RHEL: `sudo dnf install ffmpeg` (butuh repo RPM Fusion)
  - macOS: `brew install ffmpeg`
- **yt-dlp** (lihat instalasi di bawah)

Cek cepat:
```bash
ffmpeg -version | head -1
```

---

## 2. Instalasi

```bash
cd tiktok-live-toolkit
pip install -U yt-dlp            # minimal untuk perekam
# atau lengkap (termasuk viewer):
pip install -r requirements.txt
```

> Jaga yt-dlp selalu update (`pip install -U yt-dlp`). TikTok sering ubah
> internalnya; yt-dlp versi lama bisa gagal resolve.

---

## 3. PEREKAM — `recorder.py`

Pantau akun-akun TikTok. Begitu sebuah akun LIVE, langsung direkam. Saat live
berakhir/putus, recorder menunggu dan otomatis merekam sesi berikutnya.

### Cara pakai

```bash
# sebut username langsung (tanpa @)
python recorder.py charlidamelio khaby.lame

# atau dari file daftar akun
python recorder.py --file accounts.txt --out /data/recordings --poll 30
```

### Opsi

| Opsi      | Default        | Keterangan                                  |
|-----------|----------------|---------------------------------------------|
| `--out`   | `./recordings` | folder output                               |
| `--poll`  | `30`           | jeda (detik) cek live saat akun offline     |
| `--file`  | —              | file daftar akun (1 username/baris, `#`=komentar) |

Berhenti dengan **Ctrl+C** — semua file di-finalize dulu sebelum keluar.

### Hasil rekaman

```
recordings/
└── charlidamelio/
    ├── charlidamelio_20260612_091825.mp4
    └── charlidamelio_20260612_154210.mp4
```

Format nama: `<username>/<username>_<YYYYmmdd_HHMMSS>.mp4`

### Format file daftar akun (`accounts.txt`)

```
# 1 username per baris, tanpa @
charlidamelio
khaby.lame
# bellapoarch   <- baris ini diabaikan
```

---

## 4. VIEWER (opsional) — `viewer/`

Nonton banyak TikTok Live sekaligus di browser (grid).

```bash
cd viewer
pip install fastapi uvicorn httpx
uvicorn app:app --host 0.0.0.0 --port 8800
```

Lalu buka `viewer/index.html` di browser. Kalau backend beda host/port, ubah
baris `const API = ""` di `index.html` ke origin backend (mis. `http://localhost:8800`).
Ketik username, tekan Enter untuk menambah tile.

Backend menyediakan:
- `GET /api/resolve?user=<username>` → URL m3u8 (sudah diproksikan)
- `GET /api/proxy?url=...` → proxy playlist/segmen (mengatasi CORS)

---

## 5. Catatan penting (produksi)

- **Live panjang bisa terpecah jadi beberapa file.** URL stream TikTok ber-token
  `expire=`. Saat kedaluwarsa di tengah jalan, ffmpeg berhenti dan recorder
  me-resolve ulang sebagai file baru. Flag `-reconnect` menahan drop sesaat,
  bukan token expiry.
- **Anti-bot.** Jika `yt-dlp -g` mulai gagal massal (bukan karena akun offline),
  ganti isi fungsi `resolve()` di `recorder.py` ke *managed API* (mis. tik.tools
  `/webcast/room_video`, atau Apify) yang mengembalikan `hls_pull_url`. Pipeline
  ffmpeg-nya tetap sama.
- **Kapasitas disk.** ~1–3 GB per jam per stream. Pantau disk & buat rotasi/
  pembersihan kalau memantau banyak akun.
- **Container `.ts` lebih anti-rusak** dari `.mp4`. Kalau mau, ubah output ke
  `.ts` (buang `-movflags`) lalu remux: `ffmpeg -i in.ts -c copy out.mp4`.

---

## 6. Troubleshooting

| Gejala | Penyebab / solusi |
|--------|-------------------|
| `no stream for @user` | Akun sedang **tidak live**, atau diblokir anti-bot. Wajar saat polling. |
| `Tidak ditemukan di PATH: ffmpeg` | Pasang ffmpeg. |
| File MP4 0 byte | Update yt-dlp & ffmpeg. (Bug AAC sudah ditangani via `-bsf:a aac_adtstoasc`.) |
| Resolve sering gagal padahal live | `pip install -U yt-dlp`; kalau tetap, pakai managed API. |
| Viewer hitam / CORS error | Pastikan diakses lewat backend proxy (`/api/proxy`), bukan URL CDN langsung. |

---

## 7. Catatan hukum

Tool ini memakai endpoint TikTok yang sifatnya tidak resmi (reverse-engineered)
dan dapat melanggar Ketentuan Layanan TikTok. Merekam/menyimpan ulang siaran
orang lain juga punya pertimbangan hukum (hak cipta, privasi) tergantung
yurisdiksi dan tujuan penggunaan. Gunakan secara bertanggung jawab; pastikan
kepatuhan sesuai kebutuhanmu sendiri.
