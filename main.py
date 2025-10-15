# -*- coding: utf-8 -*-
import json, os, threading, socket, base64
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import re, hashlib, urllib.parse

HOST = "0.0.0.0"
PORT = 8080
WEB_ROOT = os.path.join(os.path.dirname(__file__), "static")

SAVED_PRINTERS = [
    {"ip": "192.168.0.190", "host": "KMCC36FF", "model": "ECOSYS P3145dn", "desc": "Экономисты", "can_scan": False},
    {"ip": "192.168.0.105", "host": "KMB68267", "model": "ECOSYS M2040dn",   "desc": "Бухгалтеры", "can_scan": True},
    {"ip": "192.168.0.24", "host": "Canon78c24e", "model": "LBP 223DW",   "desc": "Руководство", "can_scan": False},
    {"ip": "192.168.0.254", "host": "CanonXX", "model": "MF428X",   "desc": "Менеджеры", "can_scan": True}
]

GATE_PORTS = [9100, 631, 80]
PLUGIN_PORT = 8081  # порт для плагина


def tcp_open(ip: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def check_plugin_installed() -> bool:
    """Проверяет, установлен ли плагин (слушает ли порт 8081)"""
    try:
        with socket.create_connection(("127.0.0.1", PLUGIN_PORT), timeout=0.5):
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
        
        # Проверка статуса плагина
        if parsed.path == "/api/plugin-status":
            plugin_installed = check_plugin_installed()
            payload = json.dumps({"installed": plugin_installed}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
            
        if parsed.path == "/api/scan":
            items = scan_saved()
            payload = json.dumps({"items": items}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return


        # Скачивание плагина
        if parsed.path == "/dl/plugin":
            plugin_path = os.path.join(os.path.dirname(__file__), "static", "publish", "PrinterPlugin.exe")
            if not os.path.exists(plugin_path):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Plugin not found")
                return
                
            filename = "PrinterPlugin.exe"
            disp = f"attachment; filename={filename}; filename*=UTF-8''{urllib.parse.quote(filename)}"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", disp)
            self.send_header("Content-Length", str(os.path.getsize(plugin_path)))
            self.end_headers()
            
            with open(plugin_path, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return

        # Скачивание драйверов
        if parsed.path == "/dl/drivers":
            from urllib.parse import parse_qs
            q = parse_qs(parsed.query)
            model = (q.get('model') or [''])[0]
            
            if not model:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Model parameter required")
                return
            
            # Путь к драйверам (вся папка Kyocera)
            kyocera_path = os.path.join(os.path.dirname(__file__), "installer builder", "Kyocera")
            if not os.path.exists(kyocera_path):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Kyocera drivers not found")
                return
            
            # Создаем архив с драйверами
            import zipfile
            import tempfile
            
            temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            temp_zip.close()
            
            with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(kyocera_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, kyocera_path)
                        zipf.write(file_path, arcname)
            
            filename = f"{model}_drivers.zip"
            disp = f"attachment; filename={filename}; filename*=UTF-8''{urllib.parse.quote(filename)}"
            
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", disp)
            self.send_header("Content-Length", str(os.path.getsize(temp_zip.name)))
            self.end_headers()
            
            with open(temp_zip.name, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            
            # Удаляем временный файл
            os.unlink(temp_zip.name)
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        
        # Автоматическая установка через плагин
        if parsed.path == "/api/install":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                # Отправляем команду плагину
                plugin_installed = check_plugin_installed()
                if not plugin_installed:
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Plugin not installed"}, ensure_ascii=False).encode("utf-8"))
                    return
                
                # Отправляем запрос плагину
                import urllib.request
                import urllib.parse
                
                plugin_url = f"http://127.0.0.1:{PLUGIN_PORT}/install"
                req_data = json.dumps(data).encode('utf-8')
                
                req = urllib.request.Request(plugin_url, data=req_data, headers={'Content-Type': 'application/json'})
                # Увеличиваем таймаут до 2 минут для установки
                with urllib.request.urlopen(req, timeout=120) as response:
                    result = response.read().decode('utf-8')
                
                # Парсим ответ плагина
                plugin_result = json.loads(result)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(result.encode("utf-8"))
                return
                
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                error_msg = json.dumps({"error": str(e)}, ensure_ascii=False)
                self.wfile.write(error_msg.encode("utf-8"))
                return
        
        return super().do_POST()

if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__))
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"★ Web UI: http://127.0.0.1:{PORT}")
    httpd.serve_forever()
