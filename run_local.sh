#!/usr/bin/env bash
# SQLite 单机版本地启动脚本
# 用法: ./run_local.sh            前台启动全部服务 (Ctrl+C 退出)
#       ./run_local.sh stop       停止全部服务
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"
DB_DIR="$ROOT/data"
PID_DIR="$ROOT/.pids"

# ── 本地环境配置（首次自动生成 APP_SECRET_KEY 并持久化） ──
ENV_FILE="$ROOT/.env.local"
if [ ! -f "$ENV_FILE" ]; then
  SECRET="$(openssl rand -hex 32)"
  cat > "$ENV_FILE" <<EOF
APP_SECRET_KEY=$SECRET
DATABASE_URL=sqlite+aiosqlite:///$DB_DIR/consumables.db
ALLOW_INSECURE_MQTT_TLS=true
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
EOF
  echo "[run_local] generated $ENV_FILE"
fi
set -a; source "$ENV_FILE"; set +a

export AGENT_DEBUG_LOG_PATH="$ROOT/logs/debug.log"

mkdir -p "$DB_DIR" "$ROOT/logs" "$PID_DIR"

stop_all() {
  for name in frontend collector backend; do
    if [ -f "$PID_DIR/$name.pid" ]; then
      PID="$(cat "$PID_DIR/$name.pid")"
      if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null && echo "[run_local] stopped $name ($PID)"
      fi
      rm -f "$PID_DIR/$name.pid"
    fi
  done
}

if [ "${1:-}" = "stop" ]; then
  stop_all
  exit 0
fi

# ── 1. backend (FastAPI :8000) ──
(
  cd "$ROOT/backend"
  exec "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000
) > "$ROOT/logs/backend.log" 2>&1 &
echo $! > "$PID_DIR/backend.pid"
echo "[run_local] backend started (pid $(cat "$PID_DIR/backend.pid"))  -> http://localhost:8000/docs"

# ── 2. collector (MQTT 采集) ──
(
  cd "$ROOT/collector"
  exec "$VENV/bin/python" -m collector.main
) > "$ROOT/logs/collector.log" 2>&1 &
echo $! > "$PID_DIR/collector.pid"
echo "[run_local] collector started (pid $(cat "$PID_DIR/collector.pid"))"

# ── 3. frontend (Next.js :3000) ──
(
  cd "$ROOT/frontend"
  exec npm run dev
) > "$ROOT/logs/frontend.log" 2>&1 &
echo $! > "$PID_DIR/frontend.pid"
echo "[run_local] frontend started (pid $(cat "$PID_DIR/frontend.pid"))  -> http://localhost:3000"

echo ""
echo "[run_local] all services up. logs in $ROOT/logs/, stop with: ./run_local.sh stop"

trap 'echo ""; echo "[run_local] shutting down..."; stop_all; exit 0' INT TERM
wait
