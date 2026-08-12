@echo off
REM ============================================================
REM  Instalacion de dependencias - Canal 79
REM  Crea un entorno virtual local (.venv), instala las librerias
REM  de Python y el navegador que se usa como respaldo cuando
REM  Cloudflare bloquea la descarga directa.
REM
REM  Requisitos previos:
REM    - Python 3.10 o superior en el PATH
REM    - FFmpeg en el PATH (https://ffmpeg.org/download.html)
REM ============================================================

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python en el PATH.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [INFO] Creando entorno virtual .venv
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)

echo [INFO] Instalando dependencias de Python
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)

echo [INFO] Instalando el navegador de respaldo (Playwright)
.venv\Scripts\python.exe -m playwright install chromium

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo.
    echo [AVISO] No se encontro FFmpeg en el PATH.
    echo         Descargalo de https://ffmpeg.org/download.html y agregalo al PATH.
)

echo.
echo [OK] Instalacion terminada. Probala con: run.bat --check
pause
