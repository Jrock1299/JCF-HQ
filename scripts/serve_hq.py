#!/usr/bin/env python3
"""
JCF HQ server — serves React build + proxies /hq/* to :8900 + serves JSON data files.
"""
import http.server
import urllib.request
import urllib.error
import os
import json
from pathlib import Path

DIST_DIR   = Path('/root/.openclaw/hq-app/dist')
DATA_DIR   = Path('/root/.openclaw/dashboard')
PROXY_HOST = 'http://localhost:8900'
# 2026-07-28 fix: PORT env-overridable, default 8080 (the canonical
# dashboard URL). The jcf-hq systemd unit previously ran
# `python3 -m http.server 8080` from dashboard/ — that served a raw JSON
# directory listing, not the React SPA. It's now wired to invoke this
# script; systemd sets PORT=8080 explicitly.
PORT       = int(os.environ.get('PORT', '8080'))

# Serve any .json file from the dashboard directory


class HQHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f'[HQ] {self.address_string()} - {fmt % args}')

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_OPTIONS(self):
        self._handle()

    def _handle(self):
        path = self.path.split('?')[0].lstrip('/')

        # 0. Desktop-app compatibility (2026-07-28). The Chrome PWA shortcut
        #    ("JCF HQ - Mission Control.app") hardcodes /jcf_hq.html from an
        #    older build. Serve the SPA index for it so the installed app
        #    renders instead of blanking on a 404.
        if path == 'jcf_hq.html':
            self._serve_file(DIST_DIR / 'index.html')
            return

        # 1. Proxy /hq/* → localhost:8900
        if self.path.startswith('/hq/') or self.path == '/hq':
            self._proxy()
            return

        # 2. Serve JSON data files from dashboard directory
        if path.endswith('.json'):
            file_path = DATA_DIR / path
            if file_path.exists():
                self._serve_file(file_path)
                return
            # fall through to dist/ check below

        # 3. Serve static files from dist/
        candidate = DIST_DIR / path
        if candidate.exists() and candidate.is_file():
            self._serve_file(candidate)
            return

        # 4. SPA fallback — return index.html for any other GET
        if self.command == 'GET':
            self._serve_file(DIST_DIR / 'index.html')
        else:
            self._404()

    # Endpoints that involve long-running AI calls need a higher proxy timeout
    LONG_TIMEOUT_PATHS = {'/hq/parse-fliff-screenshot'}
    DEFAULT_PROXY_TIMEOUT = 30
    LONG_PROXY_TIMEOUT    = 150

    def _proxy(self):
        target = PROXY_HOST + self.path
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length else None

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ('host', 'transfer-encoding')}

        # Use a longer timeout for AI-heavy endpoints
        base_path = self.path.split('?')[0]
        timeout = self.LONG_PROXY_TIMEOUT if base_path in self.LONG_TIMEOUT_PATHS else self.DEFAULT_PROXY_TIMEOUT

        req = urllib.request.Request(target, data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ('transfer-encoding',):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            # Forward the upstream error response, including its headers (CORS etc.)
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ('transfer-encoding',):
                    self.send_header(k, v)
            # Guarantee CORS header so browsers can read the error body
            if 'access-control-allow-origin' not in {h.lower() for h in e.headers}:
                self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                self.wfile.write(e.read())
            except BrokenPipeError:
                pass
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self.send_response(502)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, PATCH, DELETE, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
                import json as _json
                self.wfile.write(_json.dumps({'ok': False, 'error': f'Proxy error: {e}'}).encode())
            except BrokenPipeError:
                pass

    def _serve_file(self, path: Path):
        ext = path.suffix.lower()
        mime_map = {
            '.html': 'text/html; charset=utf-8',
            '.js':   'application/javascript',
            '.css':  'text/css',
            '.json': 'application/json',
            '.png':  'image/png',
            '.jpg':  'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.svg':  'image/svg+xml',
            '.ico':  'image/x-icon',
            '.woff': 'font/woff',
            '.woff2':'font/woff2',
            '.ttf':  'font/ttf',
        }
        content_type = mime_map.get(ext, 'application/octet-stream')
        data = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache' if ext == '.html' else 'public, max-age=3600')
        self.end_headers()
        self.wfile.write(data)

    def _404(self):
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'Not found')


if __name__ == '__main__':
    import threading

    # Primary listener (default 8080 — the canonical dashboard URL).
    server = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), HQHandler)
    print(f'JCF HQ serving on http://0.0.0.0:{PORT}')
    print(f'  Static: {DIST_DIR}')
    print(f'  Proxy /hq/* → {PROXY_HOST}')
    print(f'  Data:   {DATA_DIR}')

    # Legacy desktop-app listener (2026-07-28). The installed Chrome PWA
    # points at :8899/jcf_hq.html from before the port change. Bind 8899 too
    # (same handler) so the desktop app works without reinstalling it. Env
    # LEGACY_PORT=0 disables.
    legacy = int(os.environ.get('LEGACY_PORT', '8899'))
    if legacy and legacy != PORT:
        legacy_server = http.server.ThreadingHTTPServer(('0.0.0.0', legacy), HQHandler)
        threading.Thread(target=legacy_server.serve_forever, daemon=True).start()
        print(f'  Legacy desktop-app listener on http://0.0.0.0:{legacy}')

    server.serve_forever()
