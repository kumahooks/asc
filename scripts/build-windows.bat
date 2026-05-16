@echo off
cd /d "%~dp0.."

call .venv\Scripts\activate.bat

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [ascension] installing pyinstaller...
    pip install pyinstaller
)

echo [ascension] building orchestrator...
pyinstaller ^
    --onefile ^
    --name ascension-orchestrator ^
    --add-data "beep.wav;." ^
    --collect-all playwright ^
    src\orchestrator.py

echo [ascension] building sniffer...
pyinstaller ^
    --onefile ^
    --name ascension-sniff ^
    --collect-all playwright ^
    src\sniff.py

echo [ascension] binaries in dist\
dir dist\ascension-*
