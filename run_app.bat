@echo off
rem Double-click to launch the afl_sim app (Develop / Play / Inspect / Lab) and open it in the browser.
rem Close this window (or press Ctrl+C) to stop the app. Double-clicking again restarts it (with the latest code).
rem Another port:  run_app.bat 8766
cd /d "%~dp0"
set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"
set "URL=http://127.0.0.1:%PORT%/"

if not exist ".venv\Scripts\python.exe" (
  echo No virtual environment found at .venv. Create it first:
  echo   py -3.13 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -e .[app]
  pause
  exit /b 1
)

rem an app already on this port (an old copy, perhaps one whose window was closed): stop it, so this starts the current code
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:%PORT% .*LISTENING"') do (
  echo Stopping the copy already running on port %PORT% ^(process %%p^)...
  taskkill /PID %%p /F >nul 2>&1
)

echo Starting afl_sim at %URL%  (close this window or press Ctrl+C to stop)
set "PYTHONIOENCODING=utf-8"
".venv\Scripts\python.exe" afl.py app --port %PORT%
if errorlevel 1 (
  echo.
  echo The app stopped with an error.
  pause
)
