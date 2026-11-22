@echo off
REM eBay Watcher - lanceur Windows. Double-clic ou : run.bat [commande]
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo [eBay Watcher] Premiere installation, creation de l'environnement Python...
    %PY% -m venv .venv || (echo Python 3.11+ introuvable : installe-le depuis https://www.python.org/downloads/ en cochant "Add to PATH" & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Echec de l'installation des dependances & pause & exit /b 1)
)

".venv\Scripts\python.exe" -m ebaywatch %*
if errorlevel 1 pause
endlocal
