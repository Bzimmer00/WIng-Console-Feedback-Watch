@echo off
setlocal
cd /d "%~dp0"
set "PY_CMD="
py -3.13 -c "import sys,struct,platform; print('WING_PYTHON_OK' if struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 'UNSUPPORTED')" 2>nul | findstr /x /c:"WING_PYTHON_OK" >nul
if not errorlevel 1 set "PY_CMD=py -3.13"
if defined PY_CMD goto :selected
py -3.12 -c "import sys,struct,platform; print('WING_PYTHON_OK' if struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 'UNSUPPORTED')" 2>nul | findstr /x /c:"WING_PYTHON_OK" >nul
if not errorlevel 1 set "PY_CMD=py -3.12"
if defined PY_CMD goto :selected
python -c "import sys,struct,platform; print('WING_PYTHON_OK' if sys.version_info[:2] in ((3,12),(3,13)) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 'UNSUPPORTED')" 2>nul | findstr /x /c:"WING_PYTHON_OK" >nul
if not errorlevel 1 set "PY_CMD=python"
if defined PY_CMD goto :selected
echo Compatible Python not found. Install Python 3.13 or 3.12 Windows installer, 64-bit x86-64.
echo https://www.python.org/downloads/windows/
echo Include the Python launcher, then run this installer again.
echo Installed launcher versions:
py -0p
pause
exit /b 1
:selected
echo Selected interpreter:
%PY_CMD% -c "import sys,platform; print(sys.executable); print(sys.version); print(platform.machine())"
if not exist .venv goto :create
.venv\Scripts\python.exe -c "import sys,struct,platform; print('WING_PYTHON_OK' if sys.version_info[:2] in ((3,12),(3,13)) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 'UNSUPPORTED')" 2>nul | findstr /x /c:"WING_PYTHON_OK" >nul
if not errorlevel 1 goto :install
if exist .venv-before-install-fix (
 echo Incompatible .venv found and its backup name is already in use.
 echo Extract this ZIP into a new folder and run Install-Windows.cmd there.
 goto :failed
)
echo Preserving incompatible environment as .venv-before-install-fix.
move .venv .venv-before-install-fix >nul
if errorlevel 1 goto :failed
:create
%PY_CMD% -m venv .venv
if errorlevel 1 goto :failed
:install
.venv\Scripts\python.exe -m pip install --upgrade --only-binary=:all: pip
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 goto :failed
set SD_ENABLE_ASIO=1
.venv\Scripts\python.exe -c "import numpy,scipy,sounddevice,PySide6,pyqtgraph; print('Dependency imports passed.')"
if errorlevel 1 goto :failed
echo Installation complete. Run Start-Windows.cmd.
pause
exit /b 0
:failed
echo Installation failed. Review the error above.
echo Prebuilt packages are required; no compiler or Visual Studio install is needed.
echo If no matching distribution is found, share the entire error and the interpreter shown above.
pause
exit /b 1
