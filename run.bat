@echo off
setlocal
cd /d "%~dp0"
if not defined DM_PORT set DM_PORT=8767
if not defined DEMO_MANAGEMENT_HOME set DEMO_MANAGEMENT_HOME=%USERPROFILE%\.demo-management
if not exist "%DEMO_MANAGEMENT_HOME%" mkdir "%DEMO_MANAGEMENT_HOME%"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if /I "%1"=="stop" goto stop
if /I "%1"=="status" goto status
start "Demo Management" /min cmd /c "set DEMO_MANAGEMENT_HOME=%DEMO_MANAGEMENT_HOME%&&set DM_PORT=%DM_PORT%&&.venv\Scripts\python.exe run.py > "%DEMO_MANAGEMENT_HOME%\server.log" 2>&1"
timeout /t 3 >nul
start http://127.0.0.1:%DM_PORT%
echo Demo Management launch requested at http://127.0.0.1:%DM_PORT%
goto end
:status
powershell -NoProfile -Command "try {(Invoke-RestMethod http://127.0.0.1:%DM_PORT%/api/health).name} catch {'Demo Management is stopped.'}"
goto end
:stop
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort %DM_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess; if($p){Stop-Process -Id $p -Force; 'Demo Management stopped.'}else{'Demo Management is not running.'}"
:end
endlocal
