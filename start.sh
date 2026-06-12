#!/usr/bin/env bash
# Jalankan recorder + player di background (Linux/CentOS).
# Server tidak "tidur", jadi tanpa caffeinate. (Cara permanen: pakai systemd.)
cd "$(dirname "$0")" || exit 1
mkdir -p logs

if pgrep -f "python3 recorder.py" >/dev/null; then
  echo "⚠️  recorder sudah berjalan (tidak dijalankan ulang)."
else
  nohup python3 recorder.py --file accounts.txt >> logs/recorder.log 2>&1 &
  echo "▶ recorder start (PID $!) -> logs/recorder.log"
fi

if pgrep -f "python3 player.py" >/dev/null; then
  echo "⚠️  player sudah berjalan (tidak dijalankan ulang)."
else
  nohup python3 player.py --port 6699 >> logs/player.log 2>&1 &
  echo "▶ player start (PID $!) -> http://<server-ip>:6699"
fi
