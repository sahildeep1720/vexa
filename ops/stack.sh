#!/usr/bin/env bash
# ops/stack.sh — single blessed entrypoint for the OpenRouter overlay stack.
#
# WHY THIS WRAPPER EXISTS:
#   * The overlay needs TWO -f files (base + docker-compose.openrouter.yml) AND
#     an explicit --env-file (compose reads .env from the first -f file's dir,
#     deploy/compose, not the repo root). Easy to get wrong by hand; this pins
#     the exact invocation in one place.
#   * Core `make down` only knows the BASE compose file, so it leaves the
#     overlay services (transcriber, standup-extractor) and the derived
#     runtime-api orphaned. `down` here tears down both files together.
#   * `up-lean` brings up only the services a standup deployment actually needs
#     and removes the dashboard/mcp extras (and silences orphan warnings).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

COMPOSE=(
  docker compose
  --env-file "$ROOT/.env"
  -f "$ROOT/deploy/compose/docker-compose.yml"
  -f "$ROOT/docker-compose.openrouter.yml"
)

# Lean set: everything a standup deployment needs and nothing more.
#   minio-init        seeds the recordings bucket (one-shot)
#   api-gateway       pulls in admin-api + meeting-api + runtime-api + redis +
#                     postgres + minio as transitive deps
#   tts-service       bot speech (join chime / prompts)
#   transcriber       OpenRouter STT adapter (overlay)
#   standup-extractor post-meeting hook target (overlay)
# dashboard + mcp are intentionally excluded (and trimmed below) — a headless
# VM standup box does not need the web UI or MCP bridge.
LEAN_SERVICES=(minio-init api-gateway tts-service transcriber standup-extractor)

usage() {
  cat <<'EOF'
Usage: ops/stack.sh <command> [args]

Commands:
  up                Bring up the FULL overlay stack (all services), pull missing images
  up-lean           Bring up only the standup-deployment services; trim dashboard + mcp
  down              Stop and remove the whole stack (base + overlay together)
  ps                Show service status
  logs [svc...]     Follow logs (-f, last 100 lines); optionally scope to services
  restart <svc>     Restart a single service
  build [svc...]    Build images (all, or only the named services)
  config            Render the merged, variable-substituted compose config

Notes:
  * --env-file and both -f files are wired in automatically.
  * up-lean is the right default for a headless standup VM.
EOF
}

cmd="${1:-}"
[ "$#" -gt 0 ] && shift || true

case "$cmd" in
  up)
    "${COMPOSE[@]}" up -d --pull=missing
    ;;
  up-lean)
    "${COMPOSE[@]}" up -d --remove-orphans --pull=missing "${LEAN_SERVICES[@]}"
    # setup-api-key (and the full `up`) start the dashboard/mcp; trim them so a
    # lean box stays lean. Non-fatal if they were never running.
    "${COMPOSE[@]}" rm -sf dashboard mcp >/dev/null 2>&1 || true
    ;;
  down)
    "${COMPOSE[@]}" down "$@"
    ;;
  ps)
    "${COMPOSE[@]}" ps "$@"
    ;;
  logs)
    "${COMPOSE[@]}" logs -f --tail=100 "$@"
    ;;
  restart)
    if [ "$#" -lt 1 ]; then
      echo "restart requires a service name" >&2
      exit 2
    fi
    "${COMPOSE[@]}" restart "$@"
    ;;
  build)
    "${COMPOSE[@]}" build "$@"
    # Also pull the bot image runtime-api spawns at runtime — it is NOT a compose
    # service, so `compose build`/`up` never fetches it. Without this a fresh host
    # 404s on /containers/create when a meeting starts.
    BOT_IMG="$(grep -E '^BROWSER_IMAGE=' "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2)"
    docker pull "${BOT_IMG:-vexaai/vexa-bot:latest}"
    ;;
  config)
    "${COMPOSE[@]}" config "$@"
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    echo >&2
    usage
    exit 2
    ;;
esac
