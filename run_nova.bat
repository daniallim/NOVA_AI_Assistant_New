@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo === Preparing MySQL database ===
python setup_database.py
echo.

python main.py
pause
