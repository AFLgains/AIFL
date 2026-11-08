@echo off
rem Double-click to launch the afl_sim app (Develop / Play / Inspect / Lab) and open it in the browser.
rem Close this window (or press Ctrl+C) to stop the app. Double-clicking again restarts it (with the latest code).
rem Another port:  run_app.bat 8766
cd /d "%~dp0"
set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"
set "URL=http://127.0.0.1:%PORT%/"

rem The environment (.venv). Three cases:
rem   1. its Python does not start (the folder was copied from another computer): move it aside to .venv.broken
rem      (a move, not a delete: it fails safely if anything is using the folder), then build a new one;
rem   2. no .venv: build one (setup.bat);
rem   3. its Python starts but the app's packages are missing: install them into it.
rem afl.py puts src/ on the path itself, so the aflsim package does not need to be installed for the app to start.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1 || (
    echo The .venv folder doesn't work on this computer ^(it was probably copied from another one^).
    if exist ".venv.broken" rmdir /s /q ".venv.broken"
    move ".venv" ".venv.broken" >nul || (
      echo Could not move .venv aside ^(is something using it?^). Close it, or delete .venv, and run this again.
      pause
      exit /b 1
    )
    echo Moved it to .venv.broken ^(delete that folder when the new environment works^).
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo First run on this computer: setting up the environment...
  call "%~dp0setup.bat" || exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, numpy" >nul 2>&1 || (
  echo Some of the app's packages are missing: installing them...
  ".venv\Scripts\python.exe" -m pip install -r requirements.lock || (
    echo The install failed ^(see the messages above^).
    pause
    exit /b 1
  )
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
