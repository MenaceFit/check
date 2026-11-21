@echo off
chcp 65001 >nul
title LBC Sniper
cd /d "%~dp0"
if not exist .venv (
  echo Lancez d'abord install.bat
  pause
  exit /b 1
)
rem Ouvre le dashboard dans le navigateur 4 secondes apres le demarrage
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8080"
.venv\Scripts\python -m lbcsniper
pause
