#!/usr/bin/env python3
"""
TikTok Recordings Player  (standalone, tanpa dependensi)
========================================================

Menyajikan UI web untuk menelusuri & memutar hasil rekaman dari folder
`recordings/`. Video yang SEDANG direkam pun bisa diputar (dukungan HTTP Range).

Jalankan:
    python3 player.py                       # baca ./recordings, port 6699
    python3 player.py --dir /data/recordings --port 6699

Lalu buka:  http://localhost:6699
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import socket
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler

try:
    from http.server import ThreadingHTTPServer          # Python 3.7+
except ImportError:                                       # fallback Python 3.6
    from http.server import HTTPServer
    from socketserver import ThreadingMixIn

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

ROOT = os.path.abspath("recordings")
VIDEO_EXT = (".mp4", ".ts", ".mkv", ".flv", ".webm")
LIVE_WINDOW = 45  # detik: file diubah <45s dianggap "sedang direkam"

PAGE = r"""<!DOCTYPE html>
<html lang="id"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TikTok Recordings</title>
<style>
  :root{--bg:#0d0d12;--panel:#16161f;--line:#262633;--text:#e8e8ef;--muted:#8a8a9a;--accent:#ff2d55;--live:#22c55e}
  *{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text)}
  header{display:flex;gap:12px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5}
  header h1{font-size:16px;margin:0;font-weight:700}
  header .sp{flex:1}
  header button{padding:7px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);cursor:pointer;font-size:13px}
  #player{position:sticky;top:53px;background:#000;z-index:4}
  #player video{width:100%;max-height:46vh;display:block;background:#000}
  #now{padding:8px 16px;font-size:13px;color:var(--muted);border-bottom:1px solid var(--line);background:var(--panel)}
  #now b{color:var(--text)}
  .acct{padding:10px 16px 4px;font-weight:700;font-size:14px;color:var(--accent);display:flex;gap:8px;align-items:center}
  .acct .count{color:var(--muted);font-weight:400;font-size:12px}
  .row{display:flex;gap:10px;align-items:center;padding:9px 16px;border-bottom:1px solid var(--line);cursor:pointer}
  .row:hover{background:var(--panel)}
  .row.active{background:#1d1d2a}
  .row .nm{flex:1;min-width:0;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .row .meta{font-size:12px;color:var(--muted);white-space:nowrap}
  .badge{font-size:11px;padding:2px 7px;border-radius:99px;background:var(--live);color:#04210f;font-weight:700}
  .empty{padding:40px 16px;text-align:center;color:var(--muted)}
  a.dl{color:var(--muted);text-decoration:none;font-size:14px;padding:0 4px}
</style></head><body>
<header>
  <h1>🎬 TikTok Recordings</h1><span class="sp"></span>
  <label style="font-size:12px;color:var(--muted)"><input type="checkbox" id="auto" checked> auto-refresh</label>
  <button onclick="load()">↻ Refresh</button>
</header>
<div id="player"><video id="v" controls playsinline></video></div>
<div id="now">Pilih sebuah rekaman untuk diputar.</div>
<div id="list"><div class="empty">memuat…</div></div>
<script>
const listEl=document.getElementById('list'), v=document.getElementById('v'), now=document.getElementById('now');
let current=null;
function fmtSize(b){if(b<1e6)return (b/1e3).toFixed(0)+' KB';if(b<1e9)return (b/1e6).toFixed(1)+' MB';return (b/1e9).toFixed(2)+' GB';}
function fmtTime(t){const d=new Date(t*1000);return d.toLocaleString();}
function play(it,el){
  current=it.url;
  document.querySelectorAll('.row.active').forEach(r=>r.classList.remove('active'));
  if(el)el.classList.add('active');
  v.src=it.url; v.play().catch(()=>{});
  now.innerHTML='▶ <b>'+it.name+'</b> &nbsp;·&nbsp; '+fmtSize(it.size)+(it.live?' &nbsp;·&nbsp; <span style="color:var(--live)">● sedang direkam</span>':'');
}
async function load(){
  let data; try{data=await (await fetch('/api/list')).json();}catch(e){listEl.innerHTML='<div class="empty">gagal memuat: '+e+'</div>';return;}
  if(!data.accounts.length){listEl.innerHTML='<div class="empty">Belum ada rekaman di folder.</div>';return;}
  let h='';
  for(const a of data.accounts){
    h+='<div class="acct">@'+a.name+' <span class="count">'+a.files.length+' file</span></div>';
    for(const f of a.files){
      h+='<div class="row" data-url="'+f.url+'">'
        +'<div class="nm">'+f.name+(f.live?' <span class="badge">LIVE</span>':'')+'</div>'
        +'<div class="meta">'+fmtSize(f.size)+' · '+fmtTime(f.mtime)+'</div>'
        +'<a class="dl" href="'+f.url+'" download title="unduh">⬇</a></div>';
    }
  }
  listEl.innerHTML=h;
  document.querySelectorAll('.row').forEach(row=>{
    const url=row.getAttribute('data-url');
    const f=data.accounts.flatMap(a=>a.files).find(x=>x.url===url);
    row.addEventListener('click',e=>{if(e.target.classList.contains('dl'))return;play(f,row);});
    if(url===current)row.classList.add('active');
  });
}
load();
setInterval(()=>{if(document.getElementById('auto').checked)load();},10000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # senyap
        pass

    # ---- routing ----
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/" or path == "/index.html":
            return self._send_html(PAGE)
        if path == "/api/list":
            return self._send_json(self._list())
        if path.startswith("/video/"):
            return self._send_video(path[len("/video/"):])
        self.send_error(404, "Not found")

    # ---- helpers ----
    def _safe_path(self, rel: str):
        rel = urllib.parse.unquote(rel)
        full = os.path.abspath(os.path.join(ROOT, rel))
        if not (full == ROOT or full.startswith(ROOT + os.sep)):
            return None  # cegah path traversal
        return full

    def _list(self):
        out = {"root": ROOT, "accounts": []}
        if not os.path.isdir(ROOT):
            return out
        now = datetime.now().timestamp()
        for acct in sorted(os.listdir(ROOT)):
            adir = os.path.join(ROOT, acct)
            if not os.path.isdir(adir):
                continue
            files = []
            for fn in os.listdir(adir):
                if not fn.lower().endswith(VIDEO_EXT):
                    continue
                fp = os.path.join(adir, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                files.append({
                    "name": fn,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "live": (now - st.st_mtime) < LIVE_WINDOW,
                    "url": "/video/" + urllib.parse.quote(f"{acct}/{fn}"),
                })
            files.sort(key=lambda x: x["mtime"], reverse=True)
            if files:
                out["accounts"].append({"name": acct, "files": files})
        return out

    def _send_html(self, body: str):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_video(self, rel: str):
        full = self._safe_path(rel)
        if not full or not os.path.isfile(full):
            return self.send_error(404, "File not found")
        size = os.path.getsize(full)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        partial = False
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                partial = True
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        try:
            with open(full, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # player melompat/menutup koneksi -> wajar


def main():
    global ROOT
    ap = argparse.ArgumentParser(description="Standalone player untuk rekaman TikTok")
    ap.add_argument("--dir", default="recordings", help="folder rekaman (default: ./recordings)")
    ap.add_argument("--port", type=int, default=6699, help="port (default: 6699)")
    ap.add_argument("--host", default="0.0.0.0", help="host bind (default: 0.0.0.0)")
    args = ap.parse_args()
    ROOT = os.path.abspath(args.dir)
    os.makedirs(ROOT, exist_ok=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = "127.0.0.1"
    print(f"📁 Folder rekaman : {ROOT}")
    print(f"🎬 Player jalan di : http://localhost:{args.port}")
    print(f"                     http://{ip}:{args.port}  (akses dari perangkat lain di jaringan)")
    print("   Ctrl+C untuk berhenti.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nberhenti.")
        srv.shutdown()


if __name__ == "__main__":
    main()