@echo off
REM ============================================================
REM  Generador de videos de mapas satelitales - Canal 79
REM  Arranca el servicio: genera el video y lo repite en los
REM  minutos configurados en configuration.json.
REM
REM  Argumentos opcionales (se pasan tal cual a main.py):
REM    run.bat --once          genera un video y termina
REM    run.bat --check         valida configuracion y entorno
REM    run.bat --no-download   usa el buffer actual, sin bajar nada
REM ============================================================

cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python en el PATH.
    echo         Instalalo desde https://www.python.org/downloads/ y marca "Add Python to PATH".
    pause
    exit /b 1
)

%PYTHON% src\main.py %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] El programa termino con codigo %EXITCODE%. Revisa log.txt
    pause
)

exit /b %EXITCODE%
