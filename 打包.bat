@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   鼠小侠 - PyInstaller 打包脚本
echo ========================================
echo.

echo 正在打包...
pyinstaller --clean --noconfirm 鼠小侠.spec

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   打包成功！
    echo   输出文件：dist\鼠小侠.exe
    echo ========================================
) else (
    echo.
    echo 打包失败，请查看上方错误信息
)

echo.
pause
