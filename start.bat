@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [错误] 需要 Python 3.11 或更高版本。
  echo 下载地址: https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"
rem 默认只听回环。Dify 等容器场景要能被网桥访问，用第二个参数或 HOST 环境变量放开：
rem   start.bat 8000 0.0.0.0
rem 放开后仍由 src/security.py 的 Host 白名单守着，不会对局域网无条件开放。
if not defined HOST set "HOST=127.0.0.1"
if not "%~2"=="" set "HOST=%~2"
set "VER=dev"
if exist VERSION set /p VER=<VERSION

echo.
echo   记忆文档 v%VER%
echo   地址: http://127.0.0.1:%PORT%
echo   未配置模型 Key 时自动进入离线抽取模式，功能与评测仍可用。
echo   按 Ctrl+C 停止服务。
echo.

start "" cmd /c "timeout /t 2 >nul & explorer http://127.0.0.1:%PORT%"
%PY% -m src.server --host %HOST% --port %PORT%

if errorlevel 1 pause
