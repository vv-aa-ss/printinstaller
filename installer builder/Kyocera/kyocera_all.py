# -*- coding: utf-8 -*-
# Printer Installer EXE
# Делает: удаление лишних очередей/драйвера, установка драйвера из ресурсов EXE, создание порта и принтера.
# Запускать от обычного пользователя — сам поднимет UAC.

import os
import sys
import shutil
import ctypes
import subprocess
import tempfile
import time
from pathlib import Path
from datetime import datetime


# === Параметры по умолчанию (можно переопределить аргументами командной строки) ===
PRN_MODEL_NAME = 'Kyocera ECOSYS M2040dn KX'    # Точное имя модели в INF
PRN_QUEUE_NAME = 'Kyocera ECOSYS M2040dn KX'    # Имя создаваемого принтера
PORT_NAME      = 'M2040dn'                      # Имя порта (PRNPORT)
HOST_OR_IP     = 'KMB68267'                     # Хост или IP
RAW_PORT       = '9100'                         # TCP порт
ARCH_VER       = '3'                             # -v 3 (тип драйвера)
ARCH_NAME      = 'Windows x64'                   # -e "Windows x64"
DRIVER_SUBDIR  = 'drivers'              # где лежат файлы драйвера внутри EXE
INF_NAME       = 'OEMSETUP.INF'                  # корневой INF

# Какие «лишние» принтеры удалить
PRINTERS_TO_REMOVE = [
    'Fax',
    'Microsoft XPS Document Writer',
    'OneNote for Windows 10',
    "Anydesk printer",
    'Kyocera ECOSYS M2040dn',
    f'{PRN_MODEL_NAME}',
]

LOG_FILE = None

# --- Настройка TWAIN
def _get_roaming_dir() -> str:
    # Надёжнее, чем USERPROFILE: сразу даёт %APPDATA% (Roaming)
    appdata = os.environ.get("APPDATA")
    if appdata and os.path.isdir(appdata):
        return appdata
    # Фоллбэк
    user_profile = os.environ.get("USERPROFILE", r"C:\Users\Public")
    return os.path.join(user_profile, "AppData", "Roaming")

def _write_text(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # CRLF важно для некоторых ini-ридеров
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)

def configure_twain(
    scanner_name: str,            # "M2040dn"
    model_display: str,           # "ECOSYS M2040dn"
    scanner_address: str,         # "KMB68267" или IP
    password_b64: str = "43srWkUjR/8=",  # как у тебя в примере
    auth: int = 0,                # 0=выкл, 1=вкл
    ssl: int = 0,                 # 0=HTTP, 1=HTTPS
    backup_existing: bool = True
) -> str:
    """
    Создаёт (или пере-создаёт) пользовательские файлы TWAIN:
      %APPDATA%\Kyocera\KM_TWAIN\RegList.ini
      %APPDATA%\Kyocera\KM_TWAIN\KM_TWAIN1.ini

    Возвращает путь к папке KM_TWAIN.
    """
    roaming = _get_roaming_dir()
    dest = os.path.join(roaming, "Kyocera", "KM_TWAIN")
    os.makedirs(dest, exist_ok=True)

    # Бэкап если уже есть (иногда MSI “зачищает” после установки)
    if backup_existing:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        for fname in ("RegList.ini", "KM_TWAIN1.ini"):
            p = os.path.join(dest, fname)
            if os.path.isfile(p):
                try:
                    os.replace(p, p + f".bak.{ts}")
                except Exception:
                    pass

    reglist_ini = (
        "[Setting]\n"
        "Type=4\n"
        "DefaultUse=1\n"
        "RegNum=1\n"
        "[Scanner1]\n"
        f"Name={scanner_name}\n"
        f"Model={model_display}\n"
        "DefFile=KM_TWAIN1.ini\n"
        "LastScan=N_LSTSCN1.xml\n"
        "ScanList=N_SCNLST1.xml\n"
        "Pos=0\n"
    )

    km_twain1_ini = (
        "[Contents]\n"
        "Unit=0\n"
        f"ScannerAddress={scanner_address}\n"
        f"SSL={ssl}\n"
        "[Authentication]\n"
        f"Auth={auth}\n"
        "UserName=\n"
        "Account=0\n"
        "ID=\n"
        f"Password={password_b64}\n"
    )

    _write_text(os.path.join(dest, "RegList.ini"), reglist_ini)
    _write_text(os.path.join(dest, "KM_TWAIN1.ini"), km_twain1_ini)

    try:
        log(f'TWAIN: создано/обновлено в "{dest}"')
    except NameError:
        pass
    return dest
# --- END

# --- УСТАНОВКА TWAIN
def _msiexec_path():
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    p64 = os.path.join(system_root, 'Sysnative', 'msiexec.exe')  # из 32-битного процесса даёт 64-битный msiexec
    p32 = os.path.join(system_root, 'System32', 'msiexec.exe')
    return p64 if os.path.exists(p64) else p32

def install_twain():
    # MSI, упакованный как Additional Files -> Destination: "TWAIN"
    msi_path = _resource_path(os.path.join('TWAIN', 'Kyocera TWAIN Driver.msi'))
    if not os.path.isfile(msi_path):
        log(f'ОШИБКА: MSI не найден: {msi_path}')
        # подсказка что реально есть в каталоге
        try:
            twain_dir = _resource_path('TWAIN')
            log('Содержимое TWAIN: ' + '; '.join(os.listdir(twain_dir)))
        except Exception as e:
            log(f'Не удалось прочитать папку TWAIN: {e}')
        return 1619

    log_path = os.path.join(tempfile.gettempdir(), 'Kyocera_TWAIN_install.log')
    cmd = f'"{_msiexec_path()}" /i "{msi_path}" /qn /norestart /l*v "{log_path}" REBOOT=ReallySuppress'
    log(f'RUN: {cmd}')
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        log(f'ОШИБКА: msiexec вернул {rc}. Лог MSI: {log_path}')
    else:
        log(f'TWAIN установлен. Лог MSI: {log_path}')
    return rc
# --- END

# --- УСТАНОВКА Quick Scan
def _resource_path(rel_path: str) -> str:
    """
    Возвращает абсолютный путь к ресурсам как при запуске из исходников,
    так и из собранного EXE (PyInstaller/auto-py-to-exe).
    """
    base_path = getattr(sys, "_MEIPASS", None)  # PyInstaller temp dir
    if base_path and os.path.exists(os.path.join(base_path, rel_path)):
        return os.path.join(base_path, rel_path)

    # рядом с EXE/скриптом
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    p = os.path.join(exe_dir, rel_path)
    if os.path.exists(p):
        return p

    # последний шанс — текущая рабочая папка
    p = os.path.abspath(rel_path)
    return p

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _create_shortcut(shortcut_path: str, target: str, working_dir: str, icon: str = None, arguments: str = ""):
    """
    Создаёт .lnк без pywin32: через временный VBScript + cscript.exe.
    Работает на чистой Windows.
    """
    vbs = r'''Set oWS = CreateObject("WScript.Shell")
Set oLink = oWS.CreateShortcut(WScript.Arguments(0))
oLink.TargetPath = WScript.Arguments(1)
oLink.WorkingDirectory = WScript.Arguments(2)
If WScript.Arguments.Count > 3 And WScript.Arguments(3) <> "" Then oLink.IconLocation = WScript.Arguments(3)
If WScript.Arguments.Count > 4 And WScript.Arguments(4) <> "" Then oLink.Arguments = WScript.Arguments(4)
oLink.Save'''
    # Пишем vbs во временный файл
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.vbs', encoding='utf-8') as f:
        f.write(vbs)
        vbs_path = f.name
    try:
        # Гарантируем наличие каталогов под ярлыки
        os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
        cmd = (
            f'cscript //nologo "{vbs_path}" '
            f'"{shortcut_path}" "{target}" "{working_dir}" "{icon or ""}" "{arguments or ""}"'
        )
        rc, out, err = run_cmd(cmd)
        if rc == 0:
            return True, ""
        return False, err or out
    finally:
        try: os.remove(vbs_path)
        except: pass

def install_quick_scan():
    # --- 8) Копируем "Quick Scan" в C:\Program Files и создаём ярлыки ---
    src_quick_scan = _resource_path("Quick Scan")  # папка, добавленная в сборку
    dest_root = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Quick Scan")

    if not os.path.isdir(src_quick_scan):
        log(f'Папка "Quick Scan" не найдена по пути: {src_quick_scan}. Пропускаю установку Quick Scan.')
        return

    log(f'Копирую "{src_quick_scan}" -> "{dest_root}"')
    try:
        # Python 3.8+: dirs_exist_ok, чтобы поддержать повторный запуск
        shutil.copytree(src_quick_scan, dest_root, dirs_exist_ok=True)
    except TypeError:
        # На случай старого Python без dirs_exist_ok
        if not os.path.exists(dest_root):
            shutil.copytree(src_quick_scan, dest_root)
        else:
            # аккуратное обновление содержимого
            for root, dirs, files in os.walk(src_quick_scan):
                rel = os.path.relpath(root, src_quick_scan)
                target_dir = os.path.join(dest_root, rel) if rel != '.' else dest_root
                _ensure_dir(target_dir)
                for f in files:
                    shutil.copy2(os.path.join(root, f), os.path.join(target_dir, f))

    target_exe = os.path.join(dest_root, "QuickScan.exe")
    if not os.path.isfile(target_exe):
        log(f'Предупреждение: исполняемый файл не найден: {target_exe}')
    else:
        log(f'Найден QuickScan.exe: {target_exe}')

    # Пути ярлыков (для всех пользователей)
    public_desktop = r"C:\Users\Public\Desktop"
    start_menu_dir = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Quick Scan"

    _ensure_dir(public_desktop)
    _ensure_dir(start_menu_dir)

    desktop_lnk = os.path.join(public_desktop, "Quick Scan.lnk")
    start_menu_lnk = os.path.join(start_menu_dir, "Quick Scan.lnk")

    ok1, err1 = _create_shortcut(desktop_lnk, target_exe, dest_root, icon=target_exe)
    if ok1:
        log(f'Создан ярлык: {desktop_lnk}')
    else:
        log(f'Не удалось создать ярлык на рабочем столе: {err1}')

    ok2, err2 = _create_shortcut(start_menu_lnk, target_exe, dest_root, icon=target_exe)
    if ok2:
        log(f'Создан ярлык: {start_menu_lnk}')
    else:
        log(f'Не удалось создать ярлык в меню Пуск: {err2}')

# --- END



# --- окна дочерних процессов скрыты
def _hidden_si():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si

def log(msg):
    global LOG_FILE
    text = time.strftime('[%Y-%m-%d %H:%M:%S] ') + str(msg)
    print(text, flush=True)
    try:
        if LOG_FILE:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(text + '\n')
    except Exception:
        pass

def _creationflags_no_window():
    # 0x08000000 = CREATE_NO_WINDOW
    return 0x08000000

def msgbox(text: str, title: str="Инсталлятор принтера", flags: int=0x40):
    # 0x40 = MB_ICONINFORMATION, 0x10 = MB_ICONERROR
    ctypes.windll.user32.MessageBoxW(None, str(text), str(title), flags | 0x1000)  # MB_SETFOREGROUND

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def elevate():
    params = ' '.join('"{}"'.format(a) for a in sys.argv[1:])
    # Если мы в "frozen" (PyInstaller EXE), НЕЛЬЗЯ передавать sys.argv[0]
    if getattr(sys, 'frozen', False):
        # Запускаем этот же EXE с теми же параметрами
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    else:
        # Обычный .py через python.exe: передаём путь к .py
        script_path = os.path.abspath(__file__)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script_path}" {params}', None, 1)


def find_admin_scripts():
    windir = os.environ.get('WINDIR', r'C:\Windows')
    # Пытаемся без редиректа: если процесс 32-битный на 64-битной ОС, используем Sysnative
    bases = [
        Path(windir) / 'System32' / 'Printing_Admin_Scripts',
        Path(windir) / 'Sysnative' / 'Printing_Admin_Scripts',  # обход WoW64
        Path(windir) / 'SysWOW64' / 'Printing_Admin_Scripts',   # на всякий случай
    ]
    locales = ['en-US', 'ru-RU', 'ru', 'en-GB']
    for base in bases:
        for loc in locales:
            p = base / loc
            if (p / 'prnmngr.vbs').exists() and (p / 'prndrvr.vbs').exists() and (p / 'prnport.vbs').exists():
                return (str(p / 'prnmngr.vbs'), str(p / 'prndrvr.vbs'), str(p / 'prnport.vbs'))
        # Фолбэк — без папки локали
        if (base / 'prnmngr.vbs').exists() and (base / 'prndrvr.vbs').exists() and (base / 'prnport.vbs').exists():
            return (str(base / 'prnmngr.vbs'), str(base / 'prndrvr.vbs'), str(base / 'prnport.vbs'))
    raise FileNotFoundError("Не найдены Printing_Admin_Scripts (prnmngr/prndrvr/prnport).")


def run_cmd(cmd, check=False, force_cscript_unicode=False):
    use_unicode = False
    cmd_str = cmd
    if force_cscript_unicode and cmd.strip().lower().startswith('cscript'):
        if ' //u' not in cmd.lower():
            cmd_str = cmd.replace('cscript', 'cscript //U', 1)
        use_unicode = True

    log(f'RUN: {cmd_str}')
    proc = subprocess.run(
        cmd_str,
        capture_output=True,
        shell=True,  # можно оставить shell=True, но окна не вспыхнут из-за флагов ниже
        startupinfo=_hidden_si(),
        creationflags=_creationflags_no_window()
    )
    if use_unicode:
        stdout = proc.stdout.decode('utf-16le', errors='replace') if proc.stdout else ''
        stderr = proc.stderr.decode('utf-16le', errors='replace') if proc.stderr else ''
    else:
        stdout = proc.stdout.decode(errors='replace') if proc.stdout else ''
        stderr = proc.stderr.decode(errors='replace') if proc.stderr else ''

    if stdout:
        log(stdout.strip())
    if stderr:
        log(stderr.strip())

    if check and proc.returncode != 0:
        raise RuntimeError(f'Команда завершилась с кодом {proc.returncode}')
    return proc.returncode, stdout, stderr



def stop_start_spooler():
    log('Перезапуск диспетчера печати (Spooler)...')
    run_cmd('sc stop Spooler')
    # Дадим драйверам выгрузиться
    time.sleep(2)
    run_cmd('sc start Spooler')
    time.sleep(2)

def extract_driver_to_temp():
    # Если собрано PyInstaller --onefile, файлы лежат в sys._MEIPASS
    # Если --onedir или просто Python — берём относительную папку проекта.
    if hasattr(sys, '_MEIPASS'):
        src = Path(sys._MEIPASS) / DRIVER_SUBDIR
    else:
        src = Path(__file__).parent / DRIVER_SUBDIR

    if not src.exists():
        raise FileNotFoundError(f'Не найдена папка драйвера: {src}')

    tmp = Path(tempfile.mkdtemp(prefix='prn_drv_'))
    dst = tmp / 'Kyocera'
    shutil.copytree(src, dst)
    log(f'Драйверы распакованы в: {dst}')
    return dst

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description=f'Автоустановка принтера {PRN_MODEL_NAME}')
    parser.add_argument('--queue', default=PRN_QUEUE_NAME, help='Имя очереди (принтера)')
    parser.add_argument('--model', default=PRN_MODEL_NAME, help='Точное имя модели из INF')
    parser.add_argument('--port',  default=PORT_NAME, help='Имя TCP-порта (prnport)')
    parser.add_argument('--host',  default=HOST_OR_IP, help='Хост/IP принтера')
    parser.add_argument('--raw',   default=RAW_PORT, help='TCP порт RAW (по умолчанию 9100)')
    parser.add_argument('--log',   default=None, help='Путь к файлу лога')
    return parser.parse_args()

def main():
    global LOG_FILE
    args = parse_args()
    if args.log:
        LOG_FILE = args.log
    else:
        # лог во временный файл рядом с драйвером
        LOG_FILE = str(Path(tempfile.gettempdir()) / f'printer_install_{int(time.time())}.log')
    log(f'Лог: {LOG_FILE}')

    if not is_admin():
        msgbox(f'Будет установлен принтер {PRN_MODEL_NAME}, ожидайте подтверждения. В следующем окне нажмите "Да" или "Разрешить".',
               'Установка', 0x40)
        log('Требуются права администратора — запрашиваю UAC...')
        elevate()
        sys.exit(0)  # <— вместо return

    prnmngr_vbs, prndrvr_vbs, prnport_vbs = find_admin_scripts()
    log(f'Найдены скрипты:\n  prnmngr: {prnmngr_vbs}\n  prndrvr: {prndrvr_vbs}\n  prnport: {prnport_vbs}')

    drv_root = extract_driver_to_temp()
    inf_path = drv_root / INF_NAME
    if not inf_path.exists():
        raise FileNotFoundError(f'Не найден {INF_NAME} в {drv_root}')

    # 1) Удаляем «лишние» принтеры (не аварийно)
    for p in PRINTERS_TO_REMOVE:
        run_cmd(f'cscript //nologo "{prnmngr_vbs}" -d -p "{p}"', force_cscript_unicode=True)

    # 2) Удаляем драйвер (если занят — перезапускаем Spooler и пробуем ещё раз)
    rc, _, err = run_cmd(f'cscript //nologo "{prndrvr_vbs}" -d -m "{args.model}" -v {ARCH_VER} -e "{ARCH_NAME}"')
    if rc != 0 and ('занят' in (err or '').lower() or 'busy' in (err or '').lower() or '0x80041001' in (err or '')):
        log('Похоже, драйвер занят. Пробую перезапуск Spooler и повтор...')
        stop_start_spooler()
        run_cmd(f'cscript //nologo "{prndrvr_vbs}" -d -m "{args.model}" -v {ARCH_VER} -e "{ARCH_NAME}"')

    # 3) Установка драйвера из распакованной папки
    cmd_install_drv = (
        f'cscript //nologo "{prndrvr_vbs}" -a -m "{args.model}" -v {ARCH_VER} '
        f'-e "{ARCH_NAME}" -i "{inf_path}" -h "{drv_root}"'
    )
    rc, _, err = run_cmd(cmd_install_drv)
    if rc != 0:
        # Иногда помогает ещё один перезапуск Spooler
        log('Не удалось установить драйвер с первой попытки — перезапускаю Spooler и повторяю.')
        stop_start_spooler()
        rc, _, err = run_cmd(cmd_install_drv, check=True)

    # 4) Создаём TCP RAW порт
    run_cmd(f'cscript //nologo "{prnport_vbs}" -a -r "{args.port}" -h "{args.host}" -o raw -n {args.raw}', check=True)

    # 5) Создаём очередь печати
    run_cmd(
        f'cscript //nologo "{prnmngr_vbs}" -a -p "{args.queue}" -m "{args.model}" -r "{args.port}"',
        check=True
    )
    # 6) Делаем принтер принтером по умолчанию
    run_cmd(
        f'cscript //nologo "{prnmngr_vbs}" -t -p "{args.queue}"',
        check=True
    )
    log(f'Принтер «{args.queue}» установлен как принтер по умолчанию.')


    # 7) === Копирование Quick Scan и содазние ярлыка ===
    install_quick_scan()

    # 8) Установка TWAIN
    install_twain()
    log(f'TWAIN установлен')

    # 9) === Настройка TWAIN ===
    configure_twain(
        scanner_name="M2040dn",
        model_display="ECOSYS M2040dn",
        scanner_address=args.host  # или явное "KMB68267"/IP
    )



    try:
        msgbox(f'Принтер «{args.queue}» установлен успешно.', 'Готово', 0x40)
    except Exception:
        pass

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        err = f'ОШИБКА: {e}\nЛог: {LOG_FILE or "см. временную папку"}'
        log(err)
        try:
            msgbox(err, 'Ошибка установки', 0x10)  # MB_ICONERROR
        except Exception:
            pass
        sys.exit(1)
