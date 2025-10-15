#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для сборки плагина в EXE файл
"""

import os
import sys
import subprocess
import shutil

def check_pyinstaller():
    """Проверяем, установлен ли PyInstaller"""
    try:
        import PyInstaller
        return True
    except ImportError:
        return False

def install_pyinstaller():
    """Устанавливаем PyInstaller"""
    print("Устанавливаем PyInstaller...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        return True
    except subprocess.CalledProcessError:
        print("Ошибка установки PyInstaller")
        return False

def build_plugin():
    """Собираем плагин в EXE"""
    print("Собираем плагин...")
    
    # Создаем директорию для сборки
    build_dir = "build"
    dist_dir = "dist"
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    
    # Команда PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",  # Один файл
        "--windowed",  # Без консоли
        "--name", "PrinterPlugin",
        "--distpath", "static/publish",  # В папку publish
        "--workpath", build_dir,
        "--specpath", ".",
        "plugin_service.py"
    ]
    
    try:
        subprocess.check_call(cmd)
        print("✅ Плагин успешно собран!")
        
        # Проверяем, что файл создался
        plugin_path = os.path.join("static", "publish", "PrinterPlugin.exe")
        if os.path.exists(plugin_path):
            size = os.path.getsize(plugin_path) / (1024 * 1024)  # MB
            print(f"📁 Файл создан: {plugin_path} ({size:.1f} MB)")
            return True
        else:
            print("❌ Файл плагина не найден")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка сборки: {e}")
        return False

def main():
    """Основная функция"""
    print("🔧 Сборка PrinterPlugin...")
    
    # Проверяем PyInstaller
    if not check_pyinstaller():
        print("PyInstaller не установлен")
        if not install_pyinstaller():
            return False
    
    # Собираем плагин
    if build_plugin():
        print("\n🎉 Плагин готов к использованию!")
        print("Файл: static/publish/PrinterPlugin.exe")
        return True
    else:
        print("\n❌ Ошибка сборки плагина")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
