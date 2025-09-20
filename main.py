# -*- coding: utf-8 -*-
import json, os, threading, socket, base64
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import re, hashlib, urllib.parse

HOST = "0.0.0.0"
PORT = 8080
WEB_ROOT = os.path.join(os.path.dirname(__file__), "static")
# путь
INSTALLER_BIN = os.path.join(os.path.dirname(__file__), "publish", "PrinterInstaller.exe")

SAVED_PRINTERS = [
    {"ip": "192.168.0.190", "host": "KMCC36FF", "model": "ECOSYS P3145dn", "desc": "Экономисты"},
    {"ip": "192.168.0.105", "host": "KMB68267", "model": "ECOSYS M2040dn",   "desc": "Бухгалтеры"},
    {"ip": "192.168.0.24", "host": "Canon78c24e", "model": "LBP 223DW",   "desc": "Руководство"},
    {"ip": "192.168.0.254", "host": "CanonXX", "model": "MF428X",   "desc": "Менеджеры"}
]

GATE_PORTS = [9100, 631, 80]

def sanitize_name(s: str, repl='_'):
    # Разрешим буквы/цифры/пробел/.-_ (кириллица тоже ок для NTFS)
    s = s.strip()
    s = re.sub(r'[^\w\s\.\-\u0400-\u04FF]', repl, s)  # кириллица \u0400-\u04FF
    s = re.sub(r'\s+', '_', s)
    return s[:50] or 'unknown'

def tcp_open(ip: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def scan_saved():
    out = [dict(p) for p in SAVED_PRINTERS]
    threads = []
    def worker(i, ip):
        ok = any(tcp_open(ip, p) for p in GATE_PORTS)
        out[i]["online"] = bool(ok)
    for i, p in enumerate(out):
        t = threading.Thread(target=worker, args=(i, p.get("ip","")), daemon=True)
        t.start(); threads.append(t)
    for t in threads: t.join(timeout=1.2)
    for p in out: p.setdefault("online", False)
    return out

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        root = WEB_ROOT
        path = path.split("?",1)[0].split("#",1)[0]
        trailing_slash = path.rstrip().endswith('/')
        try:
            path = os.path.normpath(os.path.join(root, path.lstrip('/')))
        except Exception:
            path = root
        if os.path.isdir(path):
            if trailing_slash:
                for index in ("index.html","index.htm"):
                    index = os.path.join(path, index)
                    if os.path.exists(index):
                        path = index
                        break
        return path

    def end_headers(self):
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "public, max-age=60")
        return super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/scan":
            items = scan_saved()
            payload = json.dumps({"items": items}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/dl/installer":
            from urllib.parse import parse_qs
            q = parse_qs(parsed.query)
            ip = (q.get('ip') or [''])[0]
            host = (q.get('host') or [''])[0]
            model = (q.get('model') or [''])[0]
            blob = f"{ip}|{host}|{model}"
            short = hashlib.sha1(blob.encode('utf-8')).hexdigest()[:6]

            pretty_host = sanitize_name(host)
            pretty_model = sanitize_name(model)
            filename = f"{pretty_host}_{pretty_model}.exe"

            # Правильные заголовки имени файла (RFC 5987)
            disp = f"attachment; filename={filename}; filename*=UTF-8''{urllib.parse.quote(filename)}"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", disp)
            self.send_header("Content-Length", str(os.path.getsize(INSTALLER_BIN)))
            self.end_headers()
            # отдаём файл по кусочкам
            with open(INSTALLER_BIN, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return

            self.send_response(200)
            self.send_header("Content-Type","application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            fs = os.stat(INSTALLER_BIN)
            self.send_header("Content-Length", str(fs.st_size))
            self.end_headers()
            with open(INSTALLER_BIN, "rb") as f:
                while True:
                    chunk = f.read(64*1024)
                    if not chunk: break
                    self.wfile.write(chunk)
            return

        return super().do_GET()

if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__))
    print("Installer path:", INSTALLER_BIN, "exists?", os.path.exists(INSTALLER_BIN))
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"★ Web UI: http://127.0.0.1:{PORT}")
    httpd.serve_forever()
