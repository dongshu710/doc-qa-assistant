#!/usr/bin/env sh
# 记忆文档 · 桌面客户端（macOS / Linux）
# 会先确认本机服务在跑；没跑就临时起一个，窗口关掉后一并停掉。
set -eu
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
PORT="${PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"

if ! "$PY" -c "
import urllib.request, sys
try:
    urllib.request.build_opener(urllib.request.ProxyHandler({})).open('${BASE}/api/health', timeout=2)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
  echo "本机服务未运行，正在启动（端口 ${PORT}）…"
  mkdir -p logs
  "$PY" -m src.server --port "$PORT" >logs/desktop-server.log 2>&1 &
  SERVER_PID=$!
  trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM
  i=0
  while [ "$i" -lt 20 ]; do
    sleep 0.5
    if "$PY" -c "
import urllib.request, sys
try:
    urllib.request.build_opener(urllib.request.ProxyHandler({})).open('${BASE}/api/health', timeout=2)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
      break
    fi
    i=$((i + 1))
  done
fi

"$PY" -m src.desktop --base "$BASE" "$@"
