@echo off
rem One-time setup on a new computer: builds the project's Python environment (.venv) and installs the exact package
rem versions it was built with (requirements.lock). Needs Python 3.11+ installed (3.13 recommended) and internet for
rem the first install (a few hundred MB, mostly PyTorch). run_app.bat calls this automatically when .venv is missing.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  echo The environment already exists ^(.venv^). To rebuild it, delete the .venv folder and run this again.
  goto :eof
)

rem find a Python: the launcher (3.13, then any 3.x), then python on the PATH
set "PY="
py -3.13 --version >nul 2>&1 && set "PY=py -3.13"
if not defined PY py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
  echo.
  echo Python was not found. Install Python 3.13 from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" in the installer^), then run this again.
  pause
  exit /b 1
)
echo Using: %PY%
%PY% --version

echo.
echo [1/3] Creating the environment (.venv)...
%PY% -m venv .venv || goto :fail
echo [2/3] Installing the packages (first time: several minutes, PyTorch is large)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.lock || goto :fail
echo [3/3] Installing afl_sim itself...
".venv\Scripts\python.exe" -m pip install -e . --no-deps || goto :fail
echo.
echo Done. Start the app with run_app.bat
exit /b 0

:fail
echo.
echo Setup failed (see the messages above). Fix the problem, delete the .venv folder, and run setup.bat again.
pause
exit /b 1
