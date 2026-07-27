@echo off
chcp 65001 >nul
REM ================================================================================
REM 鼠小侠 - 一键打包脚本
REM ================================================================================
REM 功能：自动安装依赖并打包为单文件exe
REM 使用：双击运行即可
REM ================================================================================

echo.
echo ========================================
echo   鼠小侠 - 一键打包脚本
echo ========================================
echo.

REM 设置Python路径（根据实际环境修改）
set PYTHON_PATH=C:\Users\Administrator\.real\.bin\python-3.12-windows-x64\python.exe

REM 检查Python是否存在
if not exist "%PYTHON_PATH%" (
    echo [错误] 未找到Python解释器，请修改脚本中的PYTHON_PATH变量
    echo 当前设置的路径: %PYTHON_PATH%
    pause
    exit /b 1
)

echo [步骤1] 检查并安装依赖...
echo.
%PYTHON_PATH% -m pip install pyautogui pynput pyinstaller --user -q

echo [步骤2] 开始打包...
echo.
%PYTHON_PATH% -m PyInstaller --noconfirm --onefile --windowed --name "鼠小侠" --collect-submodules pynput --collect-submodules pyautogui mouse_recorder_pro.py

echo.
echo ========================================
if exist "dist\鼠小侠.exe" (
    echo   打包成功！
    echo   输出文件: dist\鼠小侠.exe
) else (
    echo   打包失败，请检查错误信息
)
echo ========================================
echo.

pause
