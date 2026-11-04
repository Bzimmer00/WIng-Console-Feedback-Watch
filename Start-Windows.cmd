@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo Run Install-Windows.cmd first in this folder.
 pause
 exit /b 1
)
set SD_ENABLE_ASIO=1
.venv\Scripts\python.exe -c "import numpy,scipy,sounddevice,PySide6,pyqtgraph" >nul 2>nul
if errorlevel 1 (
 echo This folder's Python dependencies are incomplete.
 echo Close other copies, run Install-Windows.cmd here, then launch again.
 pause
 exit /b 1
)
.venv\Scripts\python.exe app.py
if errorlevel 1 pause
