#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"
require_venv

cd "${PROJECT_ROOT}"
log_info "检查 Git 不追踪任何 runtime env 文件"
tracked_env="$(git ls-files -c -- '*.env' '**/*.env' '.env' '**/.env' | while read -r path; do
  if [[ -e "${path}" ]]; then
    printf '%s\n' "${path}"
  fi
done)"
if [[ -n "${tracked_env}" ]]; then
  log_error "发现被 Git 追踪的 runtime env 文件："
  printf '%s\n' "${tracked_env}" >&2
  exit 1
fi
log_info "运行 Ruff lint"
"${VENV_DIR}/bin/ruff" check .
log_info "运行 Ruff format check"
"${VENV_DIR}/bin/ruff" format --check .
log_info "运行 pytest"
"${VENV_DIR}/bin/pytest"
