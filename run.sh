#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="${DEMO_MANAGEMENT_HOME:-$HOME/.demo-management}"
PORT="${DM_PORT:-8767}"
PID_FILE="$HOME_DIR/server.pid"
LOG_FILE="$HOME_DIR/server.log"
mkdir -p "$HOME_DIR"
status() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then echo "Demo Management is running (PID $(cat "$PID_FILE")) on http://127.0.0.1:$PORT"; else echo "Demo Management process exists but is not responding."; fi
  else echo "Demo Management is stopped."; return 1; fi
}
stop() {
  if [[ -f "$PID_FILE" ]]; then PID="$(cat "$PID_FILE")"; if kill -0 "$PID" 2>/dev/null; then kill "$PID"; for _ in {1..20}; do kill -0 "$PID" 2>/dev/null || break; sleep .25; done; fi; rm -f "$PID_FILE"; echo "Demo Management stopped."; else echo "Demo Management is not running."; fi
}
start() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then echo "Demo Management is already running."; return 0; fi
  cd "$ROOT"
  if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
  nohup env DEMO_MANAGEMENT_HOME="$HOME_DIR" DM_PORT="$PORT" .venv/bin/python run.py >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  for _ in {1..60}; do if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then echo "Demo Management started at http://127.0.0.1:$PORT"; if [[ "${NO_BROWSER:-0}" != "1" ]]; then (command -v open >/dev/null && open "http://127.0.0.1:$PORT" || command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT") >/dev/null 2>&1 || true; fi; return 0; fi; sleep 1; done
  echo "Startup timed out. Check $LOG_FILE"; return 1
}
case "${1:-start}" in start) start;; status) status;; stop) stop;; restart) stop || true; start;; *) echo "Usage: ./run.sh {start|status|stop|restart}"; exit 2;; esac
