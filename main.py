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


# ───────────────────────────────── Mini-DB (настраивай под себя) ────────────────────────────────
USER_DB: Dict[str, Dict[str, str]] = {
    "KMCC36FF": {"model": "ECOSYS P3145dn", "desc": "Принтер экономистов"},
    # "CANON719955": {"model":"MF429x", "desc":"Канцелярия"}
}

# ───────────────────────────────── Сканер: настройки ────────────────────────────────────────────
GATE_PORTS = [9100, 631, 80]
DEFAULT_PORTS = [80, 443, 515, 631, 9100]
CONNECT_FAST_1 = 0.18
CONNECT_FAST_2 = 0.30
CONNECT_FULL = 0.32
HTTP_TIMEOUT = 0.6
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

    # simple model grab from banners
    model = ""
    blob = " ".join([http_server, http_title, tls_cn])
    m = re.search(
        r"(ECOSYS\s+[A-Z0-9\-]+|TASKalfa\s+[A-Z0-9\-]+|imageRUNNER\s+ADV[^\s<]+|MF\d{3,5}[A-Za-z]?|P\d{3,5}[A-Za-z]?|B\d{3,5})",
        blob, re.IGNORECASE)
    if m: model = m.group(1)

    extra = USER_DB.get(host or "", {})
    if extra:
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


# ───────────────────────────────── Тема/стили ───────────────────────────────────────────────────
def load_qss(dark: bool) -> str:
    # Можно настроить фирменный цвет
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
    /* Кнопка "Установить" по свойству kind="install" */
    QPushButton[kind="install"] {{
        background: {acc};        /* acc/brand */
        color: white;
        border: none;
        border-radius: 12px;
        padding: 6px 14px;
        min-width: 120px;      /* делаем длинной */
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

        # карточка
        card = QFrame(objectName="Card")
        root.addWidget(card, 1)
        v = QVBoxLayout(card)
        v.setContentsMargins(32, 28, 32, 24)
        v.setSpacing(18)

        self.title = QLabel("Сканируем сеть…", objectName="Title")
        self.subtitle = QLabel("Это займёт совсем немного времени", objectName="Subtle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.title, 0)
        v.addWidget(self.subtitle, 0)

        self.pb = QProgressBar()
        self.pb.setRange(0, 100)
        v.addWidget(self.pb, 0)

        self.hint = QLabel("Подсказка: держите ПК в сети во время поиска", objectName="Subtle")
        v.addWidget(self.hint, 0)

        self._phrases = ["Собираем информацию…", "Ещё немного…", "Почти готово…"]
        self._ph_idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self.rotate_phrase)
        self._timer.start()

        self.worker = ScanWorker()
        self.worker.progress.connect(self.on_progress)
        self.worker.status.connect(self.on_status)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def apply_theme(self):
        self.app.setStyleSheet(load_qss(self.dark))
        self.app.setFont(QFont("Segoe UI", 10))

    def rotate_phrase(self):
        self._ph_idx = (self._ph_idx + 1) % len(self._phrases)
        self.title.setText(self._phrases[self._ph_idx])

    def on_status(self, text: str):
        self.statusBar().showMessage(text)

    def on_progress(self, done: int, total: int):
        self.pb.setValue(int(done * 100 / max(1, total)))

    def on_finished(self, rows: List[Dict]):
        self._timer.stop()
        if not rows:
            QMessageBox.information(self, "Ничего не найдено",
                                    f"Сканирование завершено: принтеров не обнаружено.\nЛог: {LOG_PATH}")
        logging.info(f"on_finished: rows={len(rows)}")
        self.results = ResultsWindow(self.app, rows, self.dark)
        self.results.show()
        _WinRegistry.add(self.results)  # держим ссылку
        self.hide()

    def on_error(self, msg: str):
        QMessageBox.critical(self, "Ошибка сканирования", msg)


# ───────────────────────────────── Результаты (современная таблица) ────────────────────────────
class ResultsWindow(QMainWindow):
    def __init__(self, app, rows: List[Dict], dark=False):
        super().__init__()
        self.app = app
        self.dark = dark
        self.setWindowTitle("Найденные принтеры")
        self.resize(980, 640)
        self.rows_all = rows
        self.apply_theme()

        wrap = QWidget(self)
        self.setCentralWidget(wrap)
        root = QVBoxLayout(wrap)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(16)

        # ─ верхняя панель
        toolbar_card = QFrame(objectName="Card")
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

        # ─ карточка с таблицей
        table_card = QFrame(objectName="Card")
        root.addWidget(table_card, 1)
        tv = QVBoxLayout(table_card)
        tv.setContentsMargins(16, 12, 16, 16)
        tv.setSpacing(8)

        self.tbl = QTableWidget()
        tv.addWidget(self.tbl, 1)
        self.tbl.setColumnCount(5)
        self.tbl.setHorizontalHeaderLabels(["IP", "Host", "Модель", "Описание", "Action"])
        self.tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        hdr = self.tbl.horizontalHeader()
        hdr.setStretchLastSection(False)
        # ширины задаём сами, чтобы кнопка не растягивалась
        for i in range(5):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        self.tbl.setShowGrid(False)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(44)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tbl.setWordWrap(False)

        # первичная подгонка ширин
        self.adjust_columns()

        # ─ нижняя строка состояния
        status_card = QFrame(objectName="Card")
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

    def populate(self, rows: List[Dict]):
        self.tbl.setRowCount(len(rows))
        for r, row in enumerate(rows):
            ip = row.get("ip", "")
            host = row.get("host", "")
            model = row.get("model", "")
            desc = row.get("desc", "")

            items = [ip, host, model, desc]
            for c, val in enumerate(items):
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
            self.tbl.setCellWidget(r, 4, btn)

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

        w_btn = 160  # компактная колонка для кнопки
        w_ip = 150
        w_host = int(vw * 0.30)
        w_model = int(vw * 0.22)
        w_desc = max(180, vw - (w_btn + w_ip + w_host + w_model + 24))

        self.tbl.setColumnWidth(0, w_ip)
        self.tbl.setColumnWidth(1, w_host)
        self.tbl.setColumnWidth(2, w_model)
        self.tbl.setColumnWidth(3, w_desc)
        self.tbl.setColumnWidth(4, w_btn)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.adjust_columns()


# ───────────────────────────────── Запуск со сплэшем ───────────────────────────────────────────
def show_splash_then_main():
    app = QApplication(sys.argv)

    # сплэш с фирменной картинкой
    splash_path = os.path.join(os.path.dirname(__file__), "splash.png")
    pix = QPixmap(splash_path) if os.path.exists(splash_path) else QPixmap(300, 150)
    if pix.isNull():
        pix = QPixmap(300, 150)
        pix.fill(Qt.GlobalColor.white)
    splash = QSplashScreen(pix)
    app.setStyleSheet(load_qss(dark=False))
    app.setFont(QFont("Segoe UI", 10))

    splash.show()
    app.processEvents()
    time.sleep(2.0)  # короткая пауза

    win = ProgressWindow(app, dark=False)
    win.show()
    splash.finish(win)
    app.setQuitOnLastWindowClosed(True)

    sys.exit(app.exec())


if __name__ == "__main__":
    show_splash_then_main()
