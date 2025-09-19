# -*- coding: utf-8 -*-
# PrinterScannerGUI.py — modern UI (PyQt6)
import ipaddress, platform, socket, ssl, subprocess, sys, threading, time, re, os, concurrent.futures
from html import unescape
from typing import Dict, List, Optional, Tuple

import logging, traceback, tempfile

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import (
    QApplication, QSplashScreen, QMainWindow, QWidget, QVBoxLayout, QLabel,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
    QMessageBox, QLineEdit, QHBoxLayout, QFrame, QSizePolicy
)
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QCursor, QGuiApplication

LOG_PATH = os.path.join(tempfile.gettempdir(),
                        f"PrinterInstaller_{time.strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.DEBUG,
    filename=LOG_PATH,
    filemode="w",
    format="%(asctime)s.%(msecs)03d %(levelname)s %(threadName)s: %(message)s",
    datefmt="%H:%M:%S",
)

def _excepthook(etype, value, tb):
    logging.critical("UNCAUGHT", exc_info=(etype, value, tb))
    try:
        QMessageBox.critical(None, "Критическая ошибка",
                             f"Произошла неперехваченная ошибка.\n\n{value}\n\nЛог: {LOG_PATH}")
    except Exception:
        pass

sys.excepthook = _excepthook

class _WinRegistry:
    """Держим ссылки на окна, чтобы GC их не прибил преждевременно."""
    keep: list = []

    @classmethod
    def add(cls, w):
        cls.keep.append(w)
        try:
            w.destroyed.connect(lambda *_: cls.keep.remove(w) if w in cls.keep else None)
        except Exception:
            pass

# ───────────────────────────────── Mini-DB────────────────────────────────
# Можете хранить ip/host/model/desc. Ключ — произвольный идентификатор (обычно host).
USER_DB: Dict[str, Dict[str, str]] = {
    "KMCC36FF":   {"model": "ECOSYS P3145dn", "desc": "Принтер экономистов",  "ip": "192.168.1.45"},
    "KMB68267":   {"model": "ECOSYS M2040dn", "desc": "Принтер бухгалтеров",  "ip": "192.168.1.46"},
    "P223":       {"desc":  "Canon Руководства", "host": "Canon78c24e",        "ip": "192.168.1.223"},
    "CANON719955":{"model": "Canon MF429x",   "desc": "Принтер манагеров"}   # ip/host можно не указывать
}

# ───────────────────────────────── Сканер: настройки ────────────────────────────────────────────
GATE_PORTS = [9100, 631, 80]
DEFAULT_PORTS = [80, 443, 515, 631, 9100]
CONNECT_FAST_1 = 0.18
CONNECT_FAST_2 = 0.80
CONNECT_FULL = 0.32
HTTP_TIMEOUT = 1
MAX_WORKERS = min(256, (os.cpu_count() or 4) * 32)

PRINTER_KEYWORDS = (
    "printer", "ipp", "lpd", "lp", "kyocera", "taskalfa", "ecosys", "km-mfp",
    "hp", "hewlett", "brother", "canon", "ricoh", "lexmark", "epson", "xerox",
    "toshiba", "sharp", "sindoh", "konica", "minolta", "oki", "samsung"
)

CREATE_NO_WINDOW = 0x08000000 if platform.system().lower().startswith("win") else 0
HOST_CACHE: Dict[str, str] = {}

# ───────────────────────────────── helpers (no-cmd windows) ─────────────────────────────────────
def run_cmd_silent(cmd: List[str], timeout: Optional[int] = None) -> str:
    try:
        logging.debug(f"run: {cmd} timeout={timeout}")
        if platform.system().lower().startswith("win"):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            out = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, text=True,
                startupinfo=si, creationflags=CREATE_NO_WINDOW, timeout=timeout
            )
        else:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return out
    except subprocess.CalledProcessError as e:
        logging.warning(f"cmd fail rc={e.returncode}: {cmd}\n{e.stdout}")
        return e.stdout or ""
    except Exception:
        logging.exception(f"cmd exception: {cmd}")
        return ""

# ───────────────────────────────── сеть: подсеть и примитивы ────────────────────────────────────
def default_gateway_net() -> Optional[ipaddress.IPv4Network]:
    gw = ""
    if platform.system().lower().startswith("win"):
        m = re.search(r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", run_cmd_silent(["route", "print", "-4"]))
        if m: gw = m.group(1)
    else:
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", run_cmd_silent(["ip", "route", "show", "default"]))
        if m: gw = m.group(1)
    if not gw: return None
    try:
        g = ipaddress.IPv4Address(gw)
        return ipaddress.IPv4Network((int(g) & 0xFFFFFF00, 24))
    except Exception:
        return None

def detect_subnet() -> ipaddress.IPv4Network:
    return default_gateway_net() or ipaddress.IPv4Network("192.168.0.0/24")

def tcp_open(ip: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def rdns(ip: str, timeout: float = 0.45) -> str:
    name = [""]
    def worker():
        try:
            name[0] = socket.gethostbyaddr(ip)[0]
        except Exception:
            name[0] = ""
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    return name[0]

def nbtstat_name(ip: str, timeout: float = 1.2) -> str:
    if not platform.system().lower().startswith("win"): return ""
    out = run_cmd_silent(["nbtstat", "-A", ip], timeout=timeout)
    m = re.search(r"^\s*([A-Z0-9\-_]{1,15})\s+<00>\s+UNIQUE", out, re.MULTILINE)
    return m.group(1) if m else ""

def resolve_dnsname_ptr(ip: str, timeout: float = 1.0) -> str:
    if not platform.system().lower().startswith("win"): return ""
    ps = f"Resolve-DnsName -Name {ip} -Type PTR -ErrorAction SilentlyContinue | Select-Object -ExpandProperty NameHost"
    out = run_cmd_silent(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                         timeout=timeout).strip()
    return out.rstrip(".")

def _detect_charset(headers: str, body: str) -> str:
    m = re.search(r"charset=([\w\-]+)", headers, re.IGNORECASE)
    if m: return m.group(1).lower()
    m = re.search(r"<meta[^>]+charset=['\"]?([\w\-]+)['\"]?", body, re.IGNORECASE)
    return m.group(1).lower() if m else ""

def http_fingerprint(ip: str, port: int = 80) -> Tuple[str, str]:
    try:
        s = socket.create_connection((ip, port), timeout=HTTP_TIMEOUT)
        s.sendall(b"GET / HTTP/1.1\r\nHost: %b\r\nUser-Agent: net-scan\r\nConnection: close\r\n\r\n" % ip.encode())
        data = b""
        s.settimeout(HTTP_TIMEOUT)
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            data += chunk
        s.close()
        raw = data.decode("latin-1", "ignore")
        headers, _, body = raw.partition("\r\n\r\n")
        server = ""
        m = re.search(r"^Server:\s*(.+)$", headers, re.IGNORECASE | re.MULTILINE)
        if m: server = m.group(1).strip()
        charset = _detect_charset(headers, body) or "utf-8"
        body_bytes = data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in data else b""
        try:
            bt = body_bytes.decode(charset, errors="ignore")
        except Exception:
            try:
                bt = body_bytes.decode("cp1251", "ignore")
            except Exception:
                bt = ""
        title = ""
        m = re.search(r"<title>(.*?)</title>", bt, re.IGNORECASE | re.DOTALL)
        if m: title = unescape(re.sub(r"\s+", " ", m.group(1).strip()))
        return server, title
    except Exception:
        return "", ""

def https_cert_cn(ip: str) -> str:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((ip, 443), timeout=HTTP_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=ip) as ssock:
                cert = ssock.getpeercert()
        for tup in cert.get("subject", ()):  # type: ignore[assignment]
            for k, v in tup:
                if k.lower() == "commonname": return v
    except Exception:
        pass
    return ""

def is_printer(ports_open: Dict[int, bool], hints: List[str]) -> bool:
    if ports_open.get(9100) or ports_open.get(631) or ports_open.get(515):
        return True
    for h in hints:
        low = (h or "").lower()
        if any(k in low for k in PRINTER_KEYWORDS):
            return True
    return False

def get_hostname_best(ip: str) -> str:
    if ip in HOST_CACHE:
        return HOST_CACHE[ip]
    name = rdns(ip)
    if not name:
        ptr = resolve_dnsname_ptr(ip)
        if ptr: name = ptr
    if not name:
        nb = nbtstat_name(ip)
        if nb: name = nb
    HOST_CACHE[ip] = name or ""
    return HOST_CACHE[ip]

def fast_gate(ip: str) -> bool:
    for p in GATE_PORTS:
        if tcp_open(ip, p, CONNECT_FAST_1):
            return True
    for p in GATE_PORTS:
        if tcp_open(ip, p, CONNECT_FAST_2):
            return True
    return False

def scan_one(ip: str) -> Optional[Dict]:
    if not fast_gate(ip):
        return None
    ports_open = {p: tcp_open(ip, p, CONNECT_FULL) for p in DEFAULT_PORTS}
    host = get_hostname_best(ip)
    http_server, http_title = ("", "")
    if ports_open.get(80):
        http_server, http_title = http_fingerprint(ip, 80)
    tls_cn = https_cert_cn(ip) if ports_open.get(443) else ""
    hints = [host, http_server, http_title, tls_cn]
    if not is_printer(ports_open, hints):
        return None

    # simple model grab
    model = ""
    blob = " ".join([http_server, http_title, tls_cn])
    m = re.search(
        r"(ECOSYS\s+[A-Z0-9\-]+|TASKalfa\s+[A-Z0-9\-]+|imageRUNNER\s+ADV[^\s<]+|MF\d{3,5}[A-Za-z]?|P\d{3,5}[A-Za-z]?|B\d{3,5})",
        blob, re.IGNORECASE)
    if m:
        model = m.group(1)

    extra = USER_DB.get(host or "", {})
    if not extra and model:
        extra = USER_DB.get(model, {})

    if extra:
        if not host and "host" in extra:
            host = extra["host"]
        model = extra.get("model", model)
        desc = extra.get("desc", "")
    else:
        desc = ""

    return {"ip": ip, "host": host, "model": model, "desc": desc}

def improve_missing_hosts(rows: List[Dict]) -> None:
    for r in rows:
        if r.get("host"): continue
        ip = r["ip"]
        name = rdns(ip, timeout=0.8) or resolve_dnsname_ptr(ip, timeout=1.5) or nbtstat_name(ip, timeout=1.8)
        if name:
            r["host"] = name
            HOST_CACHE[ip] = name

# === NEW === helper: сопоставление результатов скана с mini-DB
def compose_rows_from_db(scanned: List[Dict]) -> List[Dict]:
    """
    Возвращает список для таблицы из mini-DB с флагом online.
    При совпадении берём «живые» поля (ip/host/model) из результатов сканирования.
    Порядок — по IP если есть, иначе по host.
    """
    # индексы для быстрого поиска
    by_ip   = {r.get("ip"): r for r in scanned if r.get("ip")}
    by_host = {r.get("host","").lower(): r for r in scanned if r.get("host")}
    by_model= {}
    for r in scanned:
        m = (r.get("model") or "").lower()
        if m and m not in by_model:
            by_model[m] = r

    out: List[Dict] = []
    for key, rec in USER_DB.items():
        ip   = rec.get("ip", "")
        host = rec.get("host", "") or key  # если ключ — это host
        model= rec.get("model", "")
        desc = rec.get("desc", "")

        match = None
        if ip and ip in by_ip:
            match = by_ip[ip]
        elif host and host.lower() in by_host:
            match = by_host[host.lower()]
        elif model and model.lower() in by_model:
            match = by_model[model.lower()]

        online = bool(match)
        if match:
            # Подставляем фактические данные из сети
            ip    = match.get("ip", ip)
            host  = match.get("host", host)
            model = match.get("model", model)

        out.append({"online": online, "ip": ip, "host": host, "model": model, "desc": desc})

    # сортировка (по IP если есть, иначе по host)
    def ipkey(ipstr: str) -> int:
        try:
            return int(ipaddress.IPv4Address(ipstr))
        except Exception:
            return 0
    out.sort(key=lambda r: (0 if r["ip"] else 1, ipkey(r["ip"]), (r["host"] or "").lower()))
    return out

# ───────────────────────────────── Тема/стили ───────────────────────────────────────────────────
def load_qss(dark: bool) -> str:
    brand = "#2F8FFF" if not dark else "#6EA8FF"
    bg = "#F5F7FB" if not dark else "#121317"
    card = "#FFFFFF" if not dark else "#1B1D23"
    text = "#0F172A" if not dark else "#E5E7EB"
    subtx = "#64748B" if not dark else "#9CA3AF"
    acc = brand
    border = "#E5E7EB" if not dark else "#2A2D36"

    return f"""
    QWidget {{
        background: {bg};
        color: {text};
        font-family: 'Segoe UI', 'Inter', 'Roboto', sans-serif;
        font-size: 13px;
    }}
    QFrame#Card {{
        background: {card};
        border: 1px solid {border};
        border-radius: 16px;
    }}
    QFrame#ToolbarCard, QFrame#StatusCard {{
        background: transparent;
        border: none;
    }}
    QLabel#Title {{
        font-size: 22px; font-weight: 700; padding: 4px 6px;
    }}
    QLabel#Subtle {{
        color: {subtx};
    }}
    QProgressBar {{
        background: {border};
        border: none; border-radius: 10px; height: 12px;
        text-align: right; color: {subtx};
        padding-right: 6px;
    }}
    QProgressBar::chunk {{
        background: {acc}; border-radius: 10px;
    }}
    QLineEdit {{
        background: {card}; border: 1px solid {border};
        border-radius: 10px; padding: 8px 12px;
    }}
    QPushButton {{
        background: {acc}; color: white; border: none;
        padding: 8px 14px; border-radius: 10px; font-weight: 600;
    }}
    QPushButton#Ghost {{
        background: transparent; color: {acc}; border: 1px solid {acc};
        padding: 7px 13px; border-radius: 10px; font-weight: 600;
    }}
    QPushButton[kind="install"] {{
        background: {acc};
        color: white;
        border: none;
        border-radius: 12px;
        padding: 6px 14px;
        min-width: 120px;
        font-weight: 600;
    }}
    QPushButton[kind="install"]:hover  {{ filter: brightness(1.08); }}
    QPushButton[kind="install"]:pressed{{ transform: translateY(1px); }}

    QPushButton:hover {{ filter: brightness(110%); }}
    QPushButton:disabled {{ background: #9aa7b1; color: #f0f0f0; }}
    QTableWidget {{
        background: {card}; border: 1px solid {border}; border-radius: 12px;
        gridline-color: transparent;
    }}
    QHeaderView::section {{
        background: transparent; color: {subtx};
        border: none; border-bottom: 1px solid {border};
        padding: 10px 6px; font-weight: 600;
    }}
    QTableWidget::item {{
        padding: 8px;
    }}
    QTableWidget::item:selected {{
        background: rgba(47,143,255,0.13);
        color: {text};
    }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 8px 2px 8px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {border}; border-radius: 5px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0px; background: none;
    }}
    """

# ───────────────────────────────── Worker (параллельный) ───────────────────────────────────────
class ScanWorker(QThread):
    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self):
        try:
            logging.info("Worker started")
            net = detect_subnet()
            hosts = [str(h) for h in net.hosts()]
            total = len(hosts)
            self.status.emit(f"Сканируем {net.with_prefixlen}…")
            rows: List[Dict] = []
            done = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futures = {ex.submit(scan_one, ip): ip for ip in hosts}
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        res = fut.result()
                        if res:
                            rows.append(res)
                    except Exception:
                        logging.exception("fut.result() failed")
                    done += 1
                    if done % 8 == 0 or done == total:
                        self.status.emit(f"Сканируем {net.with_prefixlen}: {done}/{total}")
                    self.progress.emit(done, total)

            improve_missing_hosts(rows)

            def ipkey(s: str) -> int:
                try:
                    return int(ipaddress.IPv4Address(s))
                except Exception:
                    return 0

            rows.sort(key=lambda r: ipkey(r["ip"]))
            logging.info(f"Worker finished ok, rows={len(rows)}")
            self.finished.emit(rows)

        except Exception:
            msg = traceback.format_exc()
            logging.critical("Worker crashed:\n" + msg)
            self.error.emit(msg)

# ───────────────────────────────── Прогресс-окно (карточка) ────────────────────────────────────
class ProgressWindow(QMainWindow):
    def __init__(self, app, dark=False):
        super().__init__()
        self.app = app
        self.dark = dark
        self.setWindowTitle("Поиск сетевых принтеров")
        self.setMinimumSize(720, 300)
        self.apply_theme()

        wrap = QWidget(self)
        self.setCentralWidget(wrap)
        root = QVBoxLayout(wrap)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(18)

        card = QFrame(objectName="Card")
        root.addWidget(card, 1)
        v = QVBoxLayout(card)
        v.setContentsMargins(32, 28, 32, 24)
        v.setSpacing(18)

        self._real_progress = 0
        self._display_progress = 0
        self.title = QLabel("Сканируем сеть…", objectName="Title")
        self.subtitle = QLabel("Это займёт совсем немного времени", objectName="Subtle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.title, 0)
        v.addWidget(self.subtitle, 0)

        self.pb = QProgressBar()
        self.pb.setRange(0, 100)
        v.addWidget(self.pb, 0)

        self._phrases = [
            "Собираем информацию…",
            "Ещё немного…",
            "Почти готово…",
            "Хм...как много устройств",
            "Заканчиваю",
            "Обрабатываю собранную информацию"
        ]
        self._ph_idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.rotate_phrase)
        self._timer.start()

        self.worker = ScanWorker()
        self.worker.progress.connect(self.on_progress)
        self.worker.status.connect(self.on_status)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(300)
        self._progress_timer.timeout.connect(self.smooth_progress)
        self._progress_timer.start()

    def apply_theme(self):
        self.app.setStyleSheet(load_qss(self.dark))
        self.app.setFont(QFont("Segoe UI", 10))

    def rotate_phrase(self):
        if self._ph_idx < len(self._phrases):
            self.title.setText(self._phrases[self._ph_idx])
            self._ph_idx += 1
        else:
            self._timer.stop()

    def on_status(self, text: str):
        self.statusBar().showMessage(text)

    def on_progress(self, done: int, total: int):
        self._real_progress = int(done * 100 / max(1, total))

    def on_finished(self, rows: List[Dict]):
        self._timer.stop()
        logging.info(f"on_finished: scanned_rows={len(rows)}")
        # === NEW === строим итоговый список из mini-DB
        final_rows = compose_rows_from_db(rows)
        self.results = ResultsWindow(self.app, final_rows, self.dark)
        self.results.show()
        _WinRegistry.add(self.results)
        self.hide()

    def on_error(self, msg: str):
        QMessageBox.critical(self, "Ошибка сканирования", msg)

    def smooth_progress(self):
        if self._display_progress < self._real_progress:
            self._display_progress += 4
            self.pb.setValue(self._display_progress)
        elif self._real_progress == 100:
            self._display_progress = 100
            self.pb.setValue(100)
            self._progress_timer.stop()

# ───────────────────────────────── Результаты (современная таблица) ────────────────────────────
class ResultsWindow(QMainWindow):
    def __init__(self, app, rows: List[Dict], dark=False):
        super().__init__()
        self.app = app
        self.dark = dark
        self.setWindowTitle("Найденные принтеры")
        self.resize(980, 640)
        self.rows_all = rows   # уже включает все устройства из mini-DB
        self.apply_theme()

        wrap = QWidget(self)
        self.setCentralWidget(wrap)
        root = QVBoxLayout(wrap)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(16)

        toolbar_card = QFrame(objectName="ToolbarCard")
        root.addWidget(toolbar_card, 0)
        tl = QHBoxLayout(toolbar_card)
        tl.setContentsMargins(16, 12, 16, 12)
        tl.setSpacing(12)

        self.title = QLabel("Найденные принтеры", objectName="Title")
        tl.addWidget(self.title, 0)
        tl.addStretch(1)
        self.search = QLineEdit(placeholderText="Поиск (IP / Host / Model / Описание)")
        self.search.textChanged.connect(self.apply_filter)
        self.search.setClearButtonEnabled(True)
        tl.addWidget(self.search, 2)
        self.btn_rescan = QPushButton("🔄 Пересканировать", objectName="Ghost")
        self.btn_rescan.clicked.connect(self.rescan)
        tl.addWidget(self.btn_rescan, 0)
        self.btn_theme = QPushButton("🌙 Тема", objectName="Ghost")
        self.btn_theme.clicked.connect(self.toggle_theme)
        tl.addWidget(self.btn_theme, 0)

        table_card = QFrame(objectName="Card")
        root.addWidget(table_card, 1)
        tv = QVBoxLayout(table_card)
        tv.setContentsMargins(16, 12, 16, 16)
        tv.setSpacing(8)

        self.tbl = QTableWidget()
        tv.addWidget(self.tbl, 1)
        # === NEW === добавили колонку статуса слева
        self.tbl.setColumnCount(6)
        self.tbl.setHorizontalHeaderLabels(["✓", "IP", "Host", "Модель", "Описание", "Action"])
        self.tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        hdr = self.tbl.horizontalHeader()
        hdr.setStretchLastSection(False)
        for i in range(6):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        self.tbl.setShowGrid(False)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(44)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tbl.setWordWrap(False)

        self.adjust_columns()

        status_card = QFrame(objectName="StatusCard")
        root.addWidget(status_card, 0)
        sl = QHBoxLayout(status_card)
        sl.setContentsMargins(16, 10, 16, 10)
        sl.setSpacing(6)
        self.status = QLabel("Всего принтеров: 0", objectName="Subtle")
        sl.addWidget(self.status)
        sl.addStretch(1)

        self.populate(self.rows_all)

    def apply_theme(self):
        self.app.setStyleSheet(load_qss(self.dark))
        self.app.setFont(QFont("Segoe UI", 10))

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_theme()

    # === NEW === рисуем галочку с цветом
    def _status_widget(self, online: bool) -> QWidget:
        w = QLabel("✔")
        w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        w.setStyleSheet(f"font-weight:700; color: {'#22c55e' if online else '#f59e0b'};")  # зелёный / оранжевый
        return w

    def populate(self, rows: List[Dict]):
        self.tbl.setRowCount(len(rows))
        for r, row in enumerate(rows):
            online = bool(row.get("online"))
            ip = row.get("ip", "")
            host = row.get("host", "")
            model = row.get("model", "")
            desc = row.get("desc", "")

            # статус
            self.tbl.setCellWidget(r, 0, self._status_widget(online))

            items = [ip, host, model, desc]
            for c, val in enumerate(items, start=1):
                it = QTableWidgetItem(val)
                it.setToolTip(val or "")
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tbl.setItem(r, c, it)

            btn = QPushButton("🖨 Установить")
            btn.setObjectName("InstallBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("kind", "install")
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, ip=ip, host=host, model=model: self.on_install(ip, host, model))
            self.tbl.setCellWidget(r, 5, btn)

        if hasattr(self, "status"):
            self.status.setText(f"Всего принтеров: {len(rows)}")

    def apply_filter(self):
        q = self.search.text().strip().lower()
        if not q:
            self.populate(self.rows_all)
            return
        filtered = []
        for r in self.rows_all:
            blob = " ".join([r.get("ip", ""), r.get("host", ""), r.get("model", ""), r.get("desc", "")]).lower()
            if q in blob:
                filtered.append(r)
        self.populate(filtered)

    def on_install(self, ip: str, host: str, model: str):
        QMessageBox.information(
            self,
            "Установка (заглушка)",
            f"Подготовка установки принтера:\n\nIP: {ip}\nHost: {host or '—'}\nModel: {model or '—'}\n\n(Функционал будет реализован позже)",
        )

    def rescan(self):
        p = ProgressWindow(self.app, dark=self.dark)
        p.show()
        _WinRegistry.add(p)
        self.close()

    # адаптивные ширины — фиксируем колонку с кнопкой
    def adjust_columns(self):
        vw = max(700, self.tbl.viewport().width())
        w_status = 44
        w_btn = 160
        w_ip = 150
        w_host = int(vw * 0.28)
        w_model = int(vw * 0.20)
        w_desc = max(180, vw - (w_status + w_btn + w_ip + w_host + w_model + 24))

        self.tbl.setColumnWidth(0, w_status)
        self.tbl.setColumnWidth(1, w_ip)
        self.tbl.setColumnWidth(2, w_host)
        self.tbl.setColumnWidth(3, w_model)
        self.tbl.setColumnWidth(4, w_desc)
        self.tbl.setColumnWidth(5, w_btn)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.adjust_columns()

# ───────────────────────────────── Запуск со сплэшем ───────────────────────────────────────────
def show_splash_then_main():
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve

    app = QApplication(sys.argv)
    app.setStyleSheet(load_qss(dark=False))
    app.setFont(QFont("Segoe UI", 10))

    target_screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    splash_path = os.path.join(os.path.dirname(__file__), "splash.png")
    pix = QPixmap(splash_path) if os.path.exists(splash_path) else QPixmap(50, 25)
    if pix.isNull():
        pix = QPixmap(50, 25); pix.fill(Qt.GlobalColor.white)
    else:
        pix = pix.scaled(420, 220, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)

    splash = QSplashScreen(pix)
    splash.setWindowOpacity(0.0)

    if splash.windowHandle():
        splash.windowHandle().setScreen(target_screen)
    splash.show()
    app.processEvents()

    geo = target_screen.geometry()
    splash.move(geo.center() - splash.rect().center())

    anim_in = QPropertyAnimation(splash, b"windowOpacity")
    anim_in.setDuration(600)
    anim_in.setStartValue(0.0)
    anim_in.setEndValue(1.0)
    anim_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
    splash._anim_in = anim_in
    anim_in.start()
    _WinRegistry.add(splash)

    def start_main():
        def finish_with_main():
            win = ProgressWindow(app, dark=False)
            win.show()
            _WinRegistry.add(win)
            splash.finish(win)

        anim_out = QPropertyAnimation(splash, b"windowOpacity")
        anim_out.setDuration(250)
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.0)
        anim_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
        splash._anim_out = anim_out
        anim_out.finished.connect(finish_with_main)
        anim_out.start()

    QTimer.singleShot(2000, start_main)

    app.setQuitOnLastWindowClosed(True)
    sys.exit(app.exec())

if __name__ == "__main__":
    show_splash_then_main()
