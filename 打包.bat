@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PYTHON_PATH=

for %%P in (
  "D:/ Û–°œ¿/buildenv/py310/python.exe"
  "C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe"
  "C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe"
  "C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe"
  "C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe"
  "C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe"
) do (
  if exist "%%~P" (
    "%%~P" -c "import tkinter" >nul 2>nul
    if !errorlevel! equ 0 (
      set "PYTHON_PATH=%%~P"
      goto :found
    )
  )
)

echo [ERROR] No Python with tkinter found.
pause
exit /b 1

:found
echo [INFO] Using Python: !PYTHON_PATH!

echo [STEP] Install dependencies...
"!PYTHON_PATH!" -m pip install --quiet pyautogui pynput pyinstaller
echo [STEP] Build exe...
"!PYTHON_PATH!" -m PyInstaller --noconfirm --clean  Û–°œ¿.spec
if errorlevel 1 (
  echo [ERROR] Build failed.
  pause
  exit /b 1
)

if exist "dist\ Û–°œ¿.exe" (
  echo [OK] dist\ Û–°œ¿.exe
) else (
  echo [ERROR] dist\ Û–°œ¿.exe not found.
)

pause
