#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

MONGOD_BIN="${MONGOD_BIN:-mongod}"
MONGODB_PORT="${MONGODB_PORT:-27017}"
MONGODB_DATA_DIR="${MONGODB_DATA_DIR:-${PROJECT_ROOT}/data/mongodb}"
APP_PORT="${APP_PORT:-8000}"
OPEN_BROWSER="${OPEN_BROWSER:-true}"
MONGO_PID=""
API_PID=""

port_is_open() {
  "${VENV_DIR}/bin/python" - "$1" <<'PY'
import socket
import sys

with socket.socket() as connection:
    connection.settimeout(0.3)
    raise SystemExit(connection.connect_ex(("127.0.0.1", int(sys.argv[1]))) != 0)
PY
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
    kill "${API_PID}" 2>/dev/null || true
    wait "${API_PID}" 2>/dev/null || true
  fi
  if [[ -n "${MONGO_PID}" ]] && kill -0 "${MONGO_PID}" 2>/dev/null; then
    kill "${MONGO_PID}" 2>/dev/null || true
    wait "${MONGO_PID}" 2>/dev/null || true
  fi
  exit "${exit_code}"
}

wait_for_port() {
  local port="$1"
  local label="$2"
  local attempt
  for attempt in {1..40}; do
    if port_is_open "${port}"; then
      log_info "${label} 已就绪"
      return 0
    fi
    sleep 0.25
  done
  log_error "等待 ${label} 超时，请查看上方启动日志"
  return 1
}

require_venv
trap cleanup EXIT INT TERM

if port_is_open "${MONGODB_PORT}"; then
  log_info "检测到 MongoDB 已在 127.0.0.1:${MONGODB_PORT} 运行，直接复用"
else
  if ! command -v "${MONGOD_BIN}" >/dev/null 2>&1; then
    log_error "找不到 MongoDB server command: ${MONGOD_BIN}"
    log_error "macOS 可运行: brew tap mongodb/brew && brew install mongodb-community"
    exit 1
  fi
  mkdir -p "${MONGODB_DATA_DIR}"
  log_info "正在启动 MongoDB"
  "${MONGOD_BIN}" --dbpath "${MONGODB_DATA_DIR}" --bind_ip 127.0.0.1 \
    --port "${MONGODB_PORT}" >"${MONGODB_DATA_DIR}/demo-mongodb.log" 2>&1 &
  MONGO_PID=$!
  wait_for_port "${MONGODB_PORT}" "MongoDB"
fi

if port_is_open "${APP_PORT}"; then
  log_error "端口 ${APP_PORT} 已被占用。请先停止占用该端口的程序，或设置 APP_PORT。"
  exit 1
fi

log_info "正在启动演示 API"
APP_RELOAD=false APP_PORT="${APP_PORT}" "${SCRIPT_DIR}/dev.sh" &
API_PID=$!
wait_for_port "${APP_PORT}" "演示 API"

CONSUMER_URL="http://127.0.0.1:${APP_PORT}/workspace/consumer"
AGENT_URL="http://127.0.0.1:${APP_PORT}/workspace/agent"
DOCS_URL="http://127.0.0.1:${APP_PORT}/docs"

printf '\n演示环境已启动：\n'
printf '  消费者端: %s\n' "${CONSUMER_URL}"
printf '  客服端:   %s\n' "${AGENT_URL}"
printf '  API 文档: %s\n' "${DOCS_URL}"
printf '\n建议演示顺序：消费者开始咨询 -> 继续排查 -> 转人工 -> 客服刷新队列并处理。\n'
printf '按 Ctrl+C 停止本脚本启动的服务。\n\n'

if [[ "${OPEN_BROWSER}" == "true" ]] && command -v open >/dev/null 2>&1; then
  open "${CONSUMER_URL}" "${AGENT_URL}"
fi

wait "${API_PID}"
