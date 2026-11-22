@echo off
REM eBay Watcher - lanceur Windows. Double-clic ou : run.bat [commande]
setlocal
cd /d "%~dp0"

if exist ".venv\installed.ok" goto run

echo [eBay Watcher] Installation (une seule fois, environ 1 minute)...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto nopython

if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" goto nopython
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto oldpython

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto pipfail
echo ok> ".venv\installed.ok"
echo [eBay Watcher] Installation terminee.

:run
".venv\Scripts\python.exe" -m ebaywatch %*
if errorlevel 1 pause
exit /b %errorlevel%

:nopython
echo.
echo Python est introuvable. Installe Python 3.11 ou plus recent depuis
echo https://www.python.org/downloads/  en cochant la case "Add python.exe to PATH",
echo puis relance run.bat.
pause
exit /b 1

:oldpython
echo.
echo Ta version de Python est trop ancienne : il faut Python 3.11 ou plus recent.
echo Installe-le depuis https://www.python.org/downloads/ puis supprime le dossier .venv et relance run.bat.
rmdir /s /q .venv
pause
exit /b 1

:pipfail
echo.
echo L'installation des dependances a echoue (connexion internet ?). Relance run.bat pour reessayer.
pause
exit /b 1
