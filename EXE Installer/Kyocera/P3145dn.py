# -*- coding: utf-8 -*-
# Printer Installer EXE — Kyocera ECOSYS P3145dn KX
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


# === Параметры по умолчанию (можно переопределить аргументами командной строки) ===
PRN_MODEL_NAME = 'Kyocera ECOSYS P3145dn KX'    # Точное имя модели в INF
PRN_QUEUE_NAME = 'Kyocera ECOSYS P3145dn KX'    # Имя создаваемого принтера
PORT_NAME      = 'P3145dn'                      # Имя порта (PRNPORT)
HOST_OR_IP     = 'KMCC36FF'                     # Хост или IP
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
    'Kyocera ECOSYS P3145dn',
    'Kyocera ECOSYS P3145dn KX',
]

LOG_FILE = None

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
    parser = argparse.ArgumentParser(description='Автоустановка принтера Kyocera P3145dn KX')
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
        msgbox(f'Будет установлен принтер P3145, ожидайте подтверждения. При необходимости давайте разрешение.',
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

    log('Готово! Принтер установлен.')
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
