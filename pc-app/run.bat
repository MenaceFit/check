@echo off
title Quick Checkout - Demarrage
chcp 65001 >nul 2>&1
cls
echo.
echo   ⚡  Quick Checkout PC
echo   ========================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Python n'est pas installe sur ce PC.
    echo.
    echo Telechargez Python ici :
    echo   https://www.python.org/downloads/
    echo.
    echo Cochez "Add Python to PATH" lors de l'installation !
    echo.
    pause
    exit /b 1
)

echo Python detecte. Installation des dependances...
echo.
pip install pywebview --quiet --no-warn-script-location 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Impossible d'installer pywebview.
    echo Lancez : pip install pywebview
    pause
    exit /b 1
)

echo Dependances OK. Lancement de Quick Checkout...
echo.

python "%~dp0quickcheckout.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERREUR] L'application a plante ^(code %errorlevel%^).
    echo.
    echo Essayez : pip install --upgrade pywebview
    echo.
    pause
)
