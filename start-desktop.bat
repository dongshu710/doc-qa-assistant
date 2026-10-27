@echo off
rem 记忆文档 · 桌面客户端（Windows）
rem 先在本机起服务（独立窗口，关掉客户端后仍可继续用浏览器访问），再开桌面窗口。
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

rem 服务没起就起一个；已经有实例时 start 会再开一个窗口但端口占用会自行退出
start "记忆文档 服务" /min cmd /c "%PY% -m src.server --port %PORT%"
timeout /t 3 >nul

%PY% -m src.desktop --base http://127.0.0.1:%PORT%
if errorlevel 1 pause
