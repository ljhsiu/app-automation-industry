@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 支持传参覆盖端口: start_webui.bat 8010
set PORT=%1
if "%PORT%"=="" set PORT=8000

echo ============================================
echo   AMR 压测 Web UI 控制台
echo   http://127.0.0.1:%PORT%
echo ============================================
echo.

REM 1. 检查 Python
echo [1/3] 检查 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] 未找到 Python，请先安装 Python 3.10+
    echo        下载: https://python.org
    pause
    exit /b 1
)

REM 2. 检查 Web 依赖 (缺失则自动安装)
echo [2/3] 检查 Web 依赖...
python -c "import fastapi, uvicorn" >nul 2>&1
if %errorlevel% neq 0 (
    echo   正在安装 fastapi / uvicorn ...
    pip install "fastapi>=0.110.0" "uvicorn[standard]>=0.27.0"
    if %errorlevel% neq 0 (
        echo [FAIL] 依赖安装失败，请检查网络或手动执行:
        echo        pip install fastapi "uvicorn[standard]"
        pause
        exit /b 1
    )
)
echo   Web 依赖 OK

REM 3. 检查端口占用
echo [3/3] 检查端口 %PORT%...
netstat -ano | findstr "LISTENING" | findstr ":%PORT% " >nul 2>&1
if %errorlevel% equ 0 (
    echo [FAIL] 端口 %PORT% 已被占用。
    echo        可尝试其他端口: start_webui.bat 8010
    pause
    exit /b 1
)

echo.
echo 启动服务中... 关闭本窗口即停止服务（会自动清理运行中的任务）
echo.

REM 延迟 3 秒后自动打开浏览器
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:%PORT%"

python -m uvicorn webui.app:app --host 127.0.0.1 --port %PORT%

echo.
echo 服务已退出。
pause
