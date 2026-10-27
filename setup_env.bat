@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   工业自动化压测 - 环境初始化
echo   技术栈: Python + uiautomator2 + ADB
echo ============================================
echo.

REM 1. 检查 Python
echo [1/4] 检查 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] 未找到 Python，请先安装 Python 3.10+
    echo        下载: https://python.org
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   Python %%v

REM 2. 安装 Python 依赖
echo.
echo [2/4] 安装 Python 依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo   [WARN] 静默安装失败，尝试非静默安装...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo   [FAIL] 依赖安装失败
        pause
        exit /b 1
    )
)
echo   Dependencies OK

REM 3. 检查 ADB
echo.
echo [3/4] 检查 ADB...
adb --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] 未找到 ADB
    echo   请安装 Android SDK Platform Tools:
    echo     https://developer.android.com/studio/releases/platform-tools
    echo   并将 adb.exe 所在目录加入 PATH 环境变量
) else (
    for /f "tokens=1" %%v in ('adb --version 2^>^&1 ^| findstr /r "^Android"') do echo   %%v
)

REM 4. 初始化 uiautomator2 (可选，需要已连接设备)
echo.
echo [4/4] 初始化 uiautomator2...
python -m uiautomator2 init 2>nul
if %errorlevel% neq 0 (
    echo   [WARN] uiautomator2 init 失败
    echo   请先连接设备: adb connect ^<设备IP^>:5555
    echo   然后手动执行: python -m uiautomator2 init
) else (
    echo   uiautomator2 init OK
)

echo.
echo ============================================
echo   环境初始化完成！
echo.
echo   下一步:
echo   1. 确保机器人已开机并连接同一网络
echo   2. 编辑 config.yaml，设置设备 IP:
echo      device.ip: "你的机器人IP"
echo      device.serial: "你的机器人IP:5555"
echo   3. 连接设备: adb connect ^<IP^>:5555
echo   4. 运行搬运压测:
echo      cd tests ^&^& python transport_stress_test.py
echo.
echo   详细文档: CODEBUDDY_SETUP.md
echo ============================================
pause
