@echo off
chcp 65001 >nul
title LBC Sniper - Installation
cd /d "%~dp0"
echo.
echo  === Installation de LBC Sniper ===
echo.
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo  [ERREUR] Python est introuvable. Installez Python 3.10 ou plus recent depuis
  echo           https://www.python.org/downloads/  en cochant "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist .venv (
  echo  - Creation de l'environnement virtuel...
  %PY% -m venv .venv || (echo [ERREUR] creation du venv impossible & pause & exit /b 1)
)
echo  - Installation des dependances (1 a 2 minutes)...
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || (echo [ERREUR] installation impossible & pause & exit /b 1)
if not exist .env (
  copy .env.example .env >nul
  echo  - Fichier .env cree : ouvrez-le et collez votre DISCORD_TOKEN.
)
echo.
echo  Installation terminee ! Lancez maintenant start.bat
echo.
pause
