#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

detect_compose() {
  if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
    COMPOSE=(podman compose)
  elif command -v podman-compose >/dev/null 2>&1; then
    COMPOSE=(podman-compose)
  elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  else
    echo "未找到 Podman Compose、podman-compose 或 Docker Compose。" >&2
    exit 1
  fi
}

ensure_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "已生成 .env。请填写 LLM_API_KEY、LLM_MODEL 和安全密钥后重新执行。" >&2
    exit 2
  fi
  if grep -q 'replace-with-' .env; then
    echo "警告：.env 仍包含占位配置；服务可能无法完成智能规划。" >&2
  fi
}

detect_compose
ACTION="${1:-up}"

case "$ACTION" in
  up)
    ensure_env
    "${COMPOSE[@]}" up -d --build
    echo "SQ-BI 已启动：http://localhost:${SQBI_PORT:-8080}"
    ;;
  down)
    "${COMPOSE[@]}" down
    ;;
  restart)
    ensure_env
    "${COMPOSE[@]}" up -d --build --force-recreate
    ;;
  status)
    "${COMPOSE[@]}" ps
    ;;
  logs)
    "${COMPOSE[@]}" logs -f --tail=200
    ;;
  *)
    echo "用法：$0 {up|down|restart|status|logs}" >&2
    exit 2
    ;;
esac

