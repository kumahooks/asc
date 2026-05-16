@echo off
cd /d "%~dp0.."

if not exist config.json (
    echo [ascension] config.json not found
    echo [ascension] copy config.json.template to config.json and edit it
    exit /b 1
)

call .venv\Scripts\activate.bat
python -m src.sniff %*
