@echo off
chcp 65001>nul
set "PYTHONUTF8=1"
rem ============================================================
rem  Sync local Trae / WorkBuddy login state to the checkin-server.
rem  Double-click to run.
rem  Missing Python modules (requests / PyYAML / pycryptodome)
rem  are installed automatically on first run.
rem  (ASCII-only launcher v6 : self-installing deps)
rem ============================================================
title Sync login to NAS   [v6 ascii]
setlocal
set "HERE=%~dp0"
cd /d "%HERE%"

rem ---------- defaults (overridden by sync.conf and prompts) ----------
set "NAS_IP="
set "WEB_PORT=8080"
set "WEB_PASS="
set "CFG=%HERE%sync.conf"

if not exist "%CFG%" goto cfg_loaded
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%CFG%") do set "%%a=%%b"
:cfg_loaded

if "%~1"=="" goto no_args
set "NAS_IP=%~1"
:no_args
if not "%~2"=="" set "WEB_PORT=%~2"
if not "%~3"=="" set "WEB_PASS=%~3"

cls
echo ============================================================
echo   Sync login state to NAS        [v6 ascii]
echo ============================================================
echo.
echo   Press Enter to accept the default in [brackets].
echo.
echo   Before running:
echo     - Trae / WorkBuddy client already logged in
echo     - WorkBuddy client is running (token is encrypted)
echo ------------------------------------------------------------
echo.

set "ANS="
set /p "ANS=1) NAS IP or hostname [%NAS_IP%] : "
if not "%ANS%"=="" set "NAS_IP=%ANS%"

set "ANS="
set /p "ANS=2) Console port [%WEB_PORT%] : "
if not "%ANS%"=="" set "WEB_PORT=%ANS%"

set "ANS="
set /p "ANS=3) Web password (blank if none) [] : "
if not "%ANS%"=="" set "WEB_PASS=%ANS%"

set "SERVER=http://%NAS_IP%:%WEB_PORT%"

if "%NAS_IP%"=="" goto no_host

rem ---------- locate Python ----------
set "PY="
py -3 -V >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto py_ready
python -V >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto py_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined PY goto py_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto py_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if defined PY goto py_ready
goto no_py

:py_ready
echo.
echo ------------------------------------------------------------
echo   Python  : %PY%
echo   Server  : %SERVER%
echo   Script  : %HERE%sync_credentials.py
echo ------------------------------------------------------------
echo.

if not exist "%HERE%sync_credentials.py" goto no_script

rem ---------- Python modules: install on demand ----------
%PY% -c "import requests, yaml, Crypto" >nul 2>&1
if not errorlevel 1 goto deps_ready

echo [INFO] Python modules missing. Installing requests / PyYAML / pycryptodome ...
echo        Needs internet. Expected 10 to 60 seconds.
echo.
%PY% -m pip install requests PyYAML pycryptodome
%PY% -c "import requests, yaml, Crypto" >nul 2>&1
if not errorlevel 1 goto deps_ready
goto no_deps

:deps_ready

rem ---------- remember answers (no password) ----------
>"%CFG%" echo # checkin-server credential sync config - safe to edit
>>"%CFG%" echo NAS_IP=%NAS_IP%
>>"%CFG%" echo WEB_PORT=%WEB_PORT%

if not "%WEB_PASS%"=="" set "CHECKIN_WEB_PASSWORD=%WEB_PASS%"

%PY% "%HERE%sync_credentials.py" "%SERVER%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto partial

echo.
echo [DONE] Login state synced.
echo        Open %SERVER% accounts page and check "credential validity".
goto end

:partial
echo.
echo [WARN] Script exit code %RC%, some accounts may not have imported.
echo        Common causes:
echo          - WorkBuddy client not running (encrypted token)
echo          - Never logged in to Trae / WorkBuddy on this machine
echo          - Server unreachable: %SERVER%
goto end

:no_py
echo [FAIL] Python 3.9+ not found.
echo        Install from https://www.python.org/downloads/
echo        and check "Add python.exe to PATH", then run again.
goto halt

:no_host
echo [FAIL] NAS IP is required.
echo        Enter it at the prompt, or set NAS_IP in sync.conf.
goto halt

:no_script
echo [FAIL] sync_credentials.py not found in %HERE%.
echo        Put this .bat and sync_credentials.py in the same folder.
goto halt

:no_deps
echo [FAIL] Could not install Python modules: requests / PyYAML / pycryptodome.
echo        If you are behind a proxy, set it and run again, e.g.:
echo          set HTTPS_PROXY=http://127.0.0.1:7890
goto halt

:halt
echo.
pause
exit /b 1

:end
echo.
pause
endlocal
