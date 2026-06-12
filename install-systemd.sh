#!/usr/bin/env bash
# Pasang recorder & player sebagai service systemd. Jalankan dari folder toolkit.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3)"
USR="$(whoami)"
[ -z "$PY" ] && { echo "python3 tidak ditemukan"; exit 1; }
mkdir -p "$DIR/logs"

for f in tiktok-recorder tiktok-player; do
  sed -e "s#__DIR__#$DIR#g" -e "s#__PYTHON__#$PY#g" -e "s#__USER__#$USR#g" \
      "$DIR/systemd/$f.service" | sudo tee "/etc/systemd/system/$f.service" >/dev/null
  echo "→ /etc/systemd/system/$f.service"
done

sudo systemctl daemon-reload
sudo systemctl enable --now tiktok-recorder tiktok-player
echo
echo "✅ Terpasang & jalan. Cek:"
echo "   systemctl status tiktok-recorder tiktok-player"
echo "   journalctl -u tiktok-recorder -f"
echo
echo "Buka port player di firewall (kalau perlu):"
echo "   sudo firewall-cmd --permanent --add-port=6699/tcp && sudo firewall-cmd --reload"
