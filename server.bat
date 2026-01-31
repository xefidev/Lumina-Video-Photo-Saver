@echo off
REM LUMINA Media Downloader - Server Launcher
REM Запускает локальный веб-сервер с поддержкой Cobalt API proxy

color 0A
title LUMINA Server - Media Downloader
cd /d "%~dp0"

echo.
echo ========================================
echo    LUMINA Media Downloader Server
echo ========================================
echo.

REM Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не установлен на систему!
    echo Пожалуйста установите Python с https://python.org
    echo.
    pause
    exit /b 1
)

echo [INFO] Запуск сервера...
echo [INFO] Откройте браузер: http://localhost:8000
echo.

REM Запускаем сервер
python server.py 8000

pause
