#!/usr/bin/env bash
# CashGuard in Docker on Mac / Linux.
#   ./deploy/docker.sh             demo analyzer (CPU)          ./deploy/docker.sh --gpu     real model (Linux + NVIDIA)
#   ./deploy/docker.sh --tunnel    + public trycloudflare.com    ./deploy/docker.sh --logs | --down
set -euo pipefail
cd "$(dirname "$0")/.."

files=(-f docker-compose.yml); profiles=(); action=up
for a in "$@"; do
  case "$a" in
    --gpu) files+=(-f docker-compose.gpu.yml) ;;
    --tunnel) if grep -qE '^CLOUDFLARE_TUNNEL_TOKEN=\S+' .env 2>/dev/null; then profiles+=(--profile tunnel-named); else profiles+=(--profile tunnel); fi ;;
    --named) profiles+=(--profile tunnel-named) ;;
    --logs) action=logs ;;
    --down) action=down ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker Desktop and try again." >&2; exit 1; }
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example"; }

case "$action" in
  down) exec docker compose "${files[@]}" --profile tunnel --profile tunnel-named down ;;
  logs) exec docker compose "${files[@]}" ${profiles[@]+"${profiles[@]}"} logs -f --tail 200 ;;
esac

port=$(grep -E '^PORT=[0-9]+' .env | head -1 | cut -d= -f2); port=${port:-8000}
docker compose "${files[@]}" ${profiles[@]+"${profiles[@]}"} up -d --build

printf 'Waiting for the service'
for _ in $(seq 1 360); do
  curl -fsS "http://127.0.0.1:$port/ready" >/dev/null 2>&1 && break
  printf '.'; sleep 5
done; echo
curl -fsS "http://127.0.0.1:$port/ready" >/dev/null 2>&1 || { echo "Not ready yet: ./deploy/docker.sh --logs" >&2; exit 1; }

key=$(docker compose "${files[@]}" exec -T app python -c 'from backend.app.config import get_settings; print(get_settings().resolve_api_key())')
echo "CashGuard is up:  http://127.0.0.1:$port"
echo "Jury API key:     $key"
if [[ " ${profiles[*]-} " == *" tunnel "* ]]; then
  for _ in $(seq 1 30); do
    url=$(docker compose "${files[@]}" ${profiles[@]+"${profiles[@]}"} logs cloudflared 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)
    [ -n "$url" ] && break; sleep 2
  done
  echo "Public address:   ${url:-not found yet, see: docker compose logs cloudflared}"
fi
