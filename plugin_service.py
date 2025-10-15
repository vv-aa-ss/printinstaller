#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PrinterPlugin - Служба для автоматической установки принтеров
Работает как локальный HTTP-сервер на порту 8081
"""

import json
import os
import sys
import time
import subprocess
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import tempfile
import shutil
import logging
import urllib.parse

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('plugin.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PluginHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

    def do_GET(self):
        """Обработка GET запросов"""
        parsed = urlparse(self.path)
        
        if parsed.path == "/status":
            # Проверка статуса службы
            response = {"status": "running", "version": "1.0.0"}
            self.send_json_response(response)
            return
            
        elif parsed.path == "/health":
            # Health check
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
            return
            
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        """Обработка POST запросов"""
        parsed = urlparse(self.path)
        
        if parsed.path == "/install":
            self.handle_install()
            return
        else:
            self.send_error(404, "Not Found")

    def handle_install(self):
        """Обработка запроса на установку принтера"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            logger.info(f"Install request: {data}")
            
            # Валидация данных
            required_fields = ['ip', 'model', 'variant']
            for field in required_fields:
                if field not in data:
                    self.send_error(400, f"Missing required field: {field}")
                    return
            
            # Выполняем установку синхронно
            success = self.perform_installation(
                data['ip'], 
                data['model'], 
                data['variant'], 
                data.get('host', ''),
                data.get('desc', '')
            )
            
            if success:
                response = {"success": True, "message": f"Successfully installed {data['model']}"}
            else:
                response = {"success": False, "error": f"Failed to install {data['model']}"}
            
            self.send_json_response(response)
            
        except Exception as e:
            logger.error(f"Install error: {e}")
            response = {"success": False, "error": str(e)}
            self.send_json_response(response, status=500)

    def install_printer(self, data):
        """Установка принтера в отдельном потоке"""
        try:
            ip = data['ip']
            model = data['model']
            variant = data['variant']
            host = data.get('host', '')
            
            logger.info(f"Installing printer: {model} at {ip} (variant: {variant})")
            
            # Здесь должна быть логика установки принтера
            # Пока что имитируем установку
            success = self.perform_installation(ip, model, variant, host)
            
            if success:
                logger.info(f"Successfully installed {model} at {ip}")
            else:
                logger.error(f"Failed to install {model} at {ip}")
                
        except Exception as e:
            logger.error(f"Installation thread error: {e}")

    def perform_installation(self, ip, model, variant, host, desc=''):
        """Выполнение установки принтера/сканера через CMD команды"""
        try:
            logger.info(f"Installing {model} at {ip} (host: {host})")
            
            # Загружаем драйверы с сервера
            drivers_path = self.download_drivers(model)
            if not drivers_path:
                logger.error(f"Failed to download drivers for {model}")
                return False
            
            success = True
            
            # Устанавливаем принтер если нужно
            if variant in ['printer', 'all']:
                printer_success = self.install_printer_cmd(ip, model, host, desc, drivers_path)
                success = success and printer_success
            
            # Устанавливаем сканер если нужно
            if variant in ['scanner', 'all']:
                scanner_success = self.install_scanner_cmd(ip, model, host, drivers_path)
                success = success and scanner_success
            
            # Очищаем временные файлы
            self.cleanup_temp_files(drivers_path)
            
            if success:
                logger.info(f"Successfully installed {model} at {ip}")
            else:
                logger.error(f"Failed to install {model} at {ip}")
            
            return success
                
        except Exception as e:
            logger.error(f"Installation error: {e}")
            return False

    def download_drivers(self, model):
        """Загрузка драйверов с сервера"""
        try:
            import urllib.request
            import zipfile
            import tempfile
            
            # Создаем временную папку для драйверов
            temp_dir = tempfile.mkdtemp(prefix='printer_drivers_')
            
            # URL для скачивания драйверов
            url = f"http://127.0.0.1:8080/dl/drivers?model={urllib.parse.quote(model)}"
            
            logger.info(f"Downloading drivers from: {url}")
            
            # Скачиваем архив с драйверами
            zip_path = os.path.join(temp_dir, "drivers.zip")
            urllib.request.urlretrieve(url, zip_path)
            
            # Распаковываем архив
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # Удаляем zip файл
            os.remove(zip_path)
            
            # Ищем папку с драйверами
            drivers_path = None
            
            # Определяем какие INF файлы искать в зависимости от модели
            if "LBP223" in model.upper() or "MF428" in model.upper():
                inf_files = ["CNLB0MA64.INF", "CNLB0M.INF"]
            else:
                inf_files = ["OEMSETUP.INF"]
            
            # Сначала проверяем корневую папку на наличие INF файла
            for inf_file in inf_files:
                if os.path.exists(os.path.join(temp_dir, inf_file)):
                    drivers_path = temp_dir
                    break
            
            if not drivers_path:
                # Ищем папку drivers или x64/Driver
                for item in os.listdir(temp_dir):
                    item_path = os.path.join(temp_dir, item)
                    if os.path.isdir(item_path):
                        # Проверяем папку drivers
                        if item == "drivers":
                            drivers_path = item_path
                            break
                        # Проверяем папку x64/Driver для Canon
                        elif item == "x64":
                            driver_path = os.path.join(item_path, "Driver")
                            if os.path.exists(driver_path):
                                drivers_path = driver_path
                                break
                        # Проверяем, есть ли INF файл в этой подпапке
                        else:
                            for inf_file in inf_files:
                                if os.path.exists(os.path.join(item_path, inf_file)):
                                    drivers_path = item_path
                                    break
                            if drivers_path:
                                break
                            
                            # Если не нашли в корне, ищем в подпапках (например, MF429/x64/Driver)
                            for subitem in os.listdir(item_path):
                                subitem_path = os.path.join(item_path, subitem)
                                if os.path.isdir(subitem_path):
                                    # Проверяем папку x64/Driver в подпапке
                                    if subitem == "x64":
                                        driver_path = os.path.join(subitem_path, "Driver")
                                        if os.path.exists(driver_path):
                                            drivers_path = driver_path
                                            break
                                    # Проверяем INF файлы в подпапке
                                    for inf_file in inf_files:
                                        if os.path.exists(os.path.join(subitem_path, inf_file)):
                                            drivers_path = subitem_path
                                            break
                                if drivers_path:
                                    break
                            if drivers_path:
                                break
            
            if not drivers_path:
                logger.error("No drivers directory found in archive")
                return None
            
            logger.info(f"Drivers extracted to: {drivers_path}")
            return drivers_path
            
        except Exception as e:
            logger.error(f"Failed to download drivers: {e}")
            return None

    def install_printer_cmd(self, ip, model, host, desc, drivers_path):
        """Установка принтера через CMD команды (как в kyocera_print.py)"""
        try:
            logger.info(f"Installing printer: model='{model}', host='{host}', desc='{desc}'")
            # Параметры для установки - используем model, host и desc из SAVED_PRINTERS
            if "P3145" in model.upper():
                prn_model_name = 'Kyocera ECOSYS P3145dn KX'
                prn_queue_name = f'ECOSYS P3145dn ({desc})' if desc else 'ECOSYS P3145dn'
                port_name = host  # Используем host как имя порта
            elif "M2040" in model.upper():
                prn_model_name = 'Kyocera ECOSYS M2040dn KX'
                prn_queue_name = f'ECOSYS M2040dn ({desc})' if desc else 'ECOSYS M2040dn'
                port_name = host  # Используем host как имя порта
            elif "LBP223" in model.upper():
                prn_model_name = 'Canon Generic Plus UFR II'
                prn_queue_name = f'LBP223DW ({desc})' if desc else 'LBP223DW'
                port_name = host  # Используем host как имя порта
                logger.info(f"Using Canon driver: {prn_model_name}")
            elif "MF428" in model.upper():
                prn_model_name = 'Canon Generic Plus UFR II'
                prn_queue_name = f'MF428X ({desc})' if desc else 'MF428X'
                port_name = host  # Используем host как имя порта
                logger.info(f"Using Canon driver: {prn_model_name}")
            else:
                prn_model_name = f'Kyocera {model} KX'
                prn_queue_name = f'{model} ({desc})' if desc else model
                port_name = host  # Используем host как имя порта
                logger.info(f"Using Kyocera driver: {prn_model_name}")
            
            raw_port = '9100'
            arch_ver = '3'
            arch_name = 'Windows x64'
            
            # Определяем имя INF файла в зависимости от производителя
            if "LBP223" in model.upper() or "MF428" in model.upper():
                inf_name = 'CNLB0MA64.INF'  # Canon INF файл
            else:
                inf_name = 'OEMSETUP.INF'   # Kyocera INF файл
            
            # Находим INF файл
            inf_path = None
            
            # Сначала ищем в корневой папке
            if os.path.exists(os.path.join(drivers_path, inf_name)):
                inf_path = os.path.join(drivers_path, inf_name)
            else:
                # Ищем INF файл в подпапках
                for root, dirs, files in os.walk(drivers_path):
                    for file in files:
                        if file.upper() == inf_name.upper():
                            inf_path = os.path.join(root, file)
                            break
                    if inf_path:
                        break
                
                # Если не нашли конкретный файл, ищем любой INF
                if not inf_path:
                    for root, dirs, files in os.walk(drivers_path):
                        for file in files:
                            if file.upper().endswith('.INF'):
                                inf_path = os.path.join(root, file)
                                break
                        if inf_path:
                            break
            
            if not inf_path or not os.path.exists(inf_path):
                logger.error(f"INF file not found in {drivers_path}")
                return False
            
            logger.info(f"Found INF file: {inf_path}")
            
            # Находим скрипты Windows
            prnmngr_vbs, prndrvr_vbs, prnport_vbs = self.find_admin_scripts()
            logger.info(f"Found scripts: prnmngr={prnmngr_vbs}, prndrvr={prndrvr_vbs}, prnport={prnport_vbs}")
            
            # 1) Удаляем старые принтеры
            printers_to_remove = [
                'Fax',
                'Microsoft XPS Document Writer',
                'OneNote for Windows 10',
                "Anydesk printer",
                prn_model_name,
                prn_queue_name
            ]
            
            # Добавляем специфичные принтеры для M2040
            if "M2040" in model.upper():
                printers_to_remove.extend([
                    'Kyocera ECOSYS M2040dn',
                    'Kyocera ECOSYS M2040dn KX'
                ])
            
            for p in printers_to_remove:
                self.run_cmd(f'cscript //nologo "{prnmngr_vbs}" -d -p "{p}"', force_cscript_unicode=True)
            
            # 2) Удаляем старый драйвер
            rc, _, err = self.run_cmd(f'cscript //nologo "{prndrvr_vbs}" -d -m "{prn_model_name}" -v {arch_ver} -e "{arch_name}"')
            if rc != 0 and ('занят' in (err or '').lower() or 'busy' in (err or '').lower() or '0x80041001' in (err or '')):
                logger.info('Driver seems busy, restarting Spooler...')
                self.stop_start_spooler()
                self.run_cmd(f'cscript //nologo "{prndrvr_vbs}" -d -m "{prn_model_name}" -v {arch_ver} -e "{arch_name}"')
            
            # 3) Установка драйвера
            cmd_install_drv = (
                f'cscript //nologo "{prndrvr_vbs}" -a -m "{prn_model_name}" -v {arch_ver} '
                f'-e "{arch_name}" -i "{inf_path}" -h "{drivers_path}"'
            )
            rc, _, err = self.run_cmd(cmd_install_drv)
            if rc != 0:
                logger.info('Failed to install driver on first try, restarting Spooler...')
                self.stop_start_spooler()
                rc, _, err = self.run_cmd(cmd_install_drv, check=True)
            
            # 4) Создаем TCP RAW порт
            self.run_cmd(f'cscript //nologo "{prnport_vbs}" -a -r "{port_name}" -h "{host}" -o raw -n {raw_port}', check=True)
            
            # 5) Создаем очередь печати
            self.run_cmd(
                f'cscript //nologo "{prnmngr_vbs}" -a -p "{prn_queue_name}" -m "{prn_model_name}" -r "{port_name}"',
                check=True
            )
            
            # 6) Делаем принтер принтером по умолчанию
            self.run_cmd(
                f'cscript //nologo "{prnmngr_vbs}" -t -p "{prn_queue_name}"',
                check=True
            )
            
            logger.info(f'Printer "{prn_queue_name}" installed successfully as default printer')
            return True
            
        except Exception as e:
            logger.error(f"CMD installation error: {e}")
            return False

    def install_scanner_cmd(self, ip, model, host, drivers_path):
        """Установка сканера через CMD команды"""
        try:
            logger.info(f"Installing scanner for {model} at {ip}")
            
            # Находим корневую папку архива (на уровень выше drivers_path)
            archive_root = os.path.dirname(drivers_path)
            
            # Для сканера нужно установить TWAIN драйвер
            # Ищем MSI установщик в папке TWAIN_Repack
            twain_repack_path = os.path.join(archive_root, "TWAIN_Repack")
            if not os.path.exists(twain_repack_path):
                logger.error(f"TWAIN_Repack folder not found in {archive_root}")
                return False
            
            # Ищем MSI файл в папке TWAIN_Repack
            msi_file = os.path.join(twain_repack_path, "KyoceraTwain+QuickScan.msi")
            
            if not os.path.exists(msi_file):
                logger.error(f"MSI file not found: {msi_file}")
                return False
            
            # Запускаем установку TWAIN драйвера через MSI
            logger.info(f"Running TWAIN MSI installer: {msi_file}")
            # Используем /passive параметр как указано
            self.run_cmd(f'"{msi_file}" /passive', check=False)
            
            # Создаем конфигурационные файлы TWAIN
            self.create_twain_config_files(host, model)
            
            # Устанавливаем Quick Scan приложение
            quick_scan_path = os.path.join(archive_root, "Quick Scan")
            if os.path.exists(quick_scan_path):
                # Копируем Quick Scan в Program Files
                program_files = os.environ.get('ProgramFiles', 'C:\\Program Files')
                target_path = os.path.join(program_files, "Kyocera", "Quick Scan")
                
                logger.info(f"Installing Quick Scan to {target_path}")
                self.run_cmd(f'xcopy "{quick_scan_path}" "{target_path}" /E /I /Y', check=False)
                
                # Создаем ярлык на рабочем столе
                desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
                shortcut_path = os.path.join(desktop, "Quick Scan.lnk")
                exe_path = os.path.join(target_path, "QuickScan.exe")
                
                # Создаем ярлык через PowerShell
                ps_cmd = f'''
                $WshShell = New-Object -comObject WScript.Shell
                $Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
                $Shortcut.TargetPath = "{exe_path}"
                $Shortcut.Save()
                '''
                self.run_cmd(f'powershell -Command "{ps_cmd}"')
            
            logger.info(f'Scanner for {model} installed successfully')
            return True
            
        except Exception as e:
            logger.error(f"Scanner installation error: {e}")
            return False

    def create_twain_config_files(self, host, model):
        """Создание конфигурационных файлов TWAIN"""
        try:
            # Путь к папке конфигурации TWAIN
            twain_config_dir = r"C:\Users\Public\Documents\Kyocera\KM_TWAIN"
            
            # Создаем папку если не существует
            os.makedirs(twain_config_dir, exist_ok=True)
            
            # Создаем KM_TWAIN1.ini
            km_twain_content = f"""[Contents]
Unit = 1
ScannerAddress = {host}
Compression = 3
CompressionGray = 3
SSL = 1

[Authentication]
Username = 
Password = 
Auth = 
Account = 
ID = 
"""
            
            km_twain_path = os.path.join(twain_config_dir, "KM_TWAIN1.ini")
            with open(km_twain_path, 'w', encoding='utf-8') as f:
                f.write(km_twain_content)
            
            logger.info(f"Created KM_TWAIN1.ini with ScannerAddress = {host}")
            
            # Создаем RegList.ini
            reg_list_content = f"""[Scanner1]
Pos = 0
Name = TTIwNDBkbg==
Model = {model}
DefFile = KM_TWAIN1.ini
LastScan = N_LSTSCN1.xml
ScanList = N_SCNLST1.xml

[Setting]
Type = 7
DefaultUse = 1
RegNum = 1

[Scanner2]
"""
            
            reg_list_path = os.path.join(twain_config_dir, "RegList.ini")
            with open(reg_list_path, 'w', encoding='utf-8') as f:
                f.write(reg_list_content)
            
            logger.info(f"Created RegList.ini with Model = {model}")
            
        except Exception as e:
            logger.error(f"Failed to create TWAIN config files: {e}")

    def cleanup_temp_files(self, temp_path):
        """Очистка временных файлов"""
        try:
            import shutil
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path)
                logger.info(f"Cleaned up temp directory: {temp_path}")
        except Exception as e:
            logger.error(f"Failed to cleanup temp files: {e}")

    def find_admin_scripts(self):
        """Поиск скриптов Windows для управления принтерами"""
        windir = os.environ.get('WINDIR', r'C:\Windows')
        bases = [
            os.path.join(windir, 'System32', 'Printing_Admin_Scripts'),
            os.path.join(windir, 'Sysnative', 'Printing_Admin_Scripts'),
            os.path.join(windir, 'SysWOW64', 'Printing_Admin_Scripts'),
        ]
        locales = ['en-US', 'ru-RU', 'ru', 'en-GB']
        
        for base in bases:
            for loc in locales:
                p = os.path.join(base, loc)
                if (os.path.exists(os.path.join(p, 'prnmngr.vbs')) and 
                    os.path.exists(os.path.join(p, 'prndrvr.vbs')) and 
                    os.path.exists(os.path.join(p, 'prnport.vbs'))):
                    return (os.path.join(p, 'prnmngr.vbs'), 
                           os.path.join(p, 'prndrvr.vbs'), 
                           os.path.join(p, 'prnport.vbs'))
            # Фолбэк — без папки локали
            if (os.path.exists(os.path.join(base, 'prnmngr.vbs')) and 
                os.path.exists(os.path.join(base, 'prndrvr.vbs')) and 
                os.path.exists(os.path.join(base, 'prnport.vbs'))):
                return (os.path.join(base, 'prnmngr.vbs'), 
                       os.path.join(base, 'prndrvr.vbs'), 
                       os.path.join(base, 'prnport.vbs'))
        
        raise FileNotFoundError("Printing_Admin_Scripts not found")

    def run_cmd(self, cmd, check=False, force_cscript_unicode=False):
        """Выполнение CMD команды"""
        use_unicode = False
        cmd_str = cmd
        if force_cscript_unicode and cmd.strip().lower().startswith('cscript'):
            if ' //u' not in cmd.lower():
                cmd_str = cmd.replace('cscript', 'cscript //U', 1)
            use_unicode = True

        logger.info(f'RUN: {cmd_str}')
        
        # Скрываем окна дочерних процессов
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        
        proc = subprocess.run(
            cmd_str,
            capture_output=True,
            shell=True,
            startupinfo=si,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        
        if use_unicode:
            stdout = proc.stdout.decode('utf-16le', errors='replace') if proc.stdout else ''
            stderr = proc.stderr.decode('utf-16le', errors='replace') if proc.stderr else ''
        else:
            stdout = proc.stdout.decode(errors='replace') if proc.stdout else ''
            stderr = proc.stderr.decode(errors='replace') if proc.stderr else ''

        if stdout:
            # Безопасное логирование - убираем проблемные символы
            clean_stdout = stdout.strip().encode('ascii', errors='ignore').decode('ascii')
            if clean_stdout:
                logger.info(clean_stdout)
        
        if stderr:
            clean_stderr = stderr.strip().encode('ascii', errors='ignore').decode('ascii')
            if clean_stderr:
                logger.info(clean_stderr)

        if check and proc.returncode != 0:
            raise RuntimeError(f'Command failed with code {proc.returncode}')
        return proc.returncode, stdout, stderr

    def stop_start_spooler(self):
        """Перезапуск диспетчера печати"""
        logger.info('Restarting print spooler...')
        self.run_cmd('sc stop Spooler')
        time.sleep(2)
        self.run_cmd('sc start Spooler')
        time.sleep(2)


    def send_json_response(self, data, status=200):
        """Отправка JSON ответа"""
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

def is_port_available(port):
    """Проверка доступности порта"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False

def main():
    """Основная функция"""
    PORT = 8081
    
    # Проверяем доступность порта
    if not is_port_available(PORT):
        logger.error(f"Port {PORT} is already in use")
        sys.exit(1)
    
    # Создаем HTTP сервер
    server = HTTPServer(('127.0.0.1', PORT), PluginHandler)
    
    logger.info(f"PrinterPlugin service starting on port {PORT}")
    logger.info("Service is ready to handle installation requests")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as e:
        logger.error(f"Service error: {e}")
    finally:
        server.server_close()
        logger.info("Service shutdown complete")

if __name__ == "__main__":
    main()
