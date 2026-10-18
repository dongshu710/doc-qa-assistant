#!/usr/bin/env sh
# 文档问答助手 · 一键启动（macOS / Linux）
set -eu
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then
  echo "[错误] 需要 Python 3.11 或更高版本：https://www.python.org/downloads/"
  exit 1
fi

PORT="${PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

echo
echo "  文档问答助手 v1.0.0"
echo "  地址: ${URL}"
echo "  未配置模型 Key 时自动进入离线抽取模式，功能与评测仍可用。"
echo "  按 Ctrl+C 停止服务。"
echo

(
  sleep 2
  if command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  fi
) &

exec "$PY" -m src.server --port "$PORT"
