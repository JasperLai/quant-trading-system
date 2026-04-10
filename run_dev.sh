#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_LOG_DIR="$ROOT_DIR/backend/logs"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_LOG_FILE="$BACKEND_LOG_DIR/api.dev.log"
FRONTEND_LOG_FILE="$BACKEND_LOG_DIR/frontend.dev.log"

mkdir -p "$BACKEND_LOG_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 未安装，无法启动后端。"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm 未安装，无法启动前端。"
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "frontend/node_modules 不存在，请先执行: cd frontend && npm install"
  exit 1
fi

cleanup() {
  if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  wait >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

echo "启动后端: http://127.0.0.1:8000"
(
  cd "$ROOT_DIR"
  python3 -m uvicorn backend.app:app --reload --port 8000
) >"$BACKEND_LOG_FILE" 2>&1 &
BACKEND_PID=$!

echo "启动前端: http://127.0.0.1:5173"
(
  cd "$FRONTEND_DIR"
  npm run dev -- --host 127.0.0.1
) >"$FRONTEND_LOG_FILE" 2>&1 &
FRONTEND_PID=$!

sleep 2

if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
  echo "后端启动失败，日志见: $BACKEND_LOG_FILE"
  exit 1
fi

if ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
  echo "前端启动失败，日志见: $FRONTEND_LOG_FILE"
  exit 1
fi

cat <<EOF
前后端已启动:
- 后端: http://127.0.0.1:8000
- 前端: http://127.0.0.1:5173

日志文件:
- $BACKEND_LOG_FILE
- $FRONTEND_LOG_FILE

按 Ctrl+C 可同时停止前后端。
EOF

wait "$BACKEND_PID" "$FRONTEND_PID"
