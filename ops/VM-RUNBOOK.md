# VM Runbook — OpenRouter Standup Stack on a fresh Ubuntu host

Brings up the `feat/openrouter` overlay (transcriber + standup-extractor +
croniter-patched runtime-api) on a clean Ubuntu VM, schedules a daily standup
bot join, and lists the ongoing ops checks. Run as a sudo-capable user.

Conventions: `$REPO` is the absolute path to the cloned repo (e.g.
`/home/ubuntu/vexa`). The repo-root `.env` is the single source of config; the
overlay never edits it for you.

---

## 1. Install Docker Engine

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"     # then log out/in so the group applies
docker compose version              # confirm the compose v2 plugin is present
```

## 2. Clone the repo and check out the branch

```bash
git clone <your-fork-or-origin> vexa
cd vexa
git checkout feat/openrouter
REPO="$(pwd)"
```

## 3. Create `.env` (do NOT run `make env`)

Start from the core example, then append the overlay values:

```bash
cp deploy/env-example .env
cat .env.openrouter.example >> .env       # appends the overlay section
```

REQUIRED fills (edit `.env`):

- `TRANSCRIPTION_SERVICE_URL=http://transcriber:8085/v1/audio/transcriptions`
  (the overlay value — overrides the public vexa.ai default from `env-example`)
- `TRANSCRIPTION_SERVICE_TOKEN=<shared secret>` — same value in the section-1 and
  section-5 lines; the bot and the transcriber must agree.
- `OPENROUTER_API_KEY=<your key>`
- `INTERNAL_API_SECRET=<random>` — must match across meeting-api and the
  standup-extractor (one value, used by both).
- `BOT_API_TOKEN=$(openssl rand -hex 24)` — guards the runtime-api scheduler.
- `ADMIN_TOKEN=$(openssl rand -hex 24)` — replace the `changeme` default.

> IMPORTANT — IMAGE_TAG: `deploy/env-example` ships `IMAGE_TAG=latest`. KEEP it.
> Do NOT run `make env` (or `make all`) on this branch: the Makefile `env`
> target flips `IMAGE_TAG` to `dev` on any non-`main` branch (and rewrites
> `BROWSER_IMAGE` to `vexaai/vexa-bot:dev`). On `feat/openrouter` that would pull
> the wrong (dev) core images. If you already ran it, fix `.env` back:
> `sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=latest/; s|^BROWSER_IMAGE=.*|BROWSER_IMAGE=vexaai/vexa-bot:latest|' .env`

> COMPOSE_FILE: do NOT add a `COMPOSE_FILE=` line to `.env` — the compose
> Makefile `-include`s `.env` and your line would clobber its internal
> `COMPOSE_FILE`, breaking `make init-db` / `make setup-api-key`. Export it in
> your shell instead (step 5).

## 4. DOCKER_GID (Linux auto-detect)

On Linux the compose `runtime-api` service joins the host `docker` group so it
can reach `/var/run/docker.sock`. The `make` flow auto-detects it via
`getent group docker | cut -d: -f3` and writes `DOCKER_GID=<gid>` to `.env`.
Set it explicitly to be safe:

```bash
echo "DOCKER_GID=$(getent group docker | cut -d: -f3)" >> .env
```

The Mac/OrbStack `DOCKER_GID=0` hack from the local dev notes is NOT needed on a
Linux VM — the socket is owned by the `docker` group there, not root.

## 5. Shell exports for bare `docker compose` (optional)

`ops/stack.sh` always passes `-f` explicitly, so this is only for convenience
when you run `docker compose` directly. Add to `~/.bashrc` and re-source:

```bash
echo 'export COMPOSE_FILE="'"$REPO"'/deploy/compose/docker-compose.yml:'"$REPO"'/docker-compose.openrouter.yml"' >> ~/.bashrc
echo 'export COMPOSE_PATH_SEPARATOR=":"' >> ~/.bashrc
source ~/.bashrc
```

`make` is immune (it sets its own `COMPOSE_FILE`); `ops/stack.sh` is immune
(explicit `-f`).

## 6. Bring up the lean stack

```bash
ops/stack.sh up-lean
```

This builds the overlay images (transcriber, standup-extractor,
runtime-api-cron) and starts only the standup-deployment services, pulling core
images at `IMAGE_TAG`. First run takes a few minutes (image build + pulls).

## 7. Initialize the database and seed an API key

```bash
make -C deploy/compose init-db          # create schema / run migrations
make -C deploy/compose setup-api-key    # create a user + write VEXA_API_KEY to .env
```

> `setup-api-key` starts the `dashboard` (and pulls in `mcp`) as a side effect
> of its image-tag compose-up. On a headless box you don't want them, so:

```bash
ops/stack.sh up-lean                    # run AGAIN — trims dashboard + mcp
```

## 8. Schedule the daily standup

```bash
ops/schedule-standup.sh add <google-meet-id> --time 10:30 --tz Asia/Kolkata --days mon-fri
```

`<google-meet-id>` is the `abc-defg-hij` slug from the meeting URL. The command
preflights your `VEXA_API_KEY` against the gateway, computes the UTC cron
(remapping the day-of-week when IST→UTC crosses midnight), and prints the next
run in both UTC and local time. Verify it stuck:

```bash
ops/schedule-standup.sh list
```

## 9. Verification curls

```bash
curl -fsS http://localhost:8085/health && echo "  transcriber OK"
curl -fsS http://localhost:8086/health && echo "  standup-extractor OK"
curl -fsS http://localhost:8090/health && echo "  runtime-api OK"
# api-gateway (auth required) — expect 200 with your key:
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "X-API-Key: $(grep -E '^VEXA_API_KEY=' .env | cut -d= -f2)" \
  http://localhost:8056/bots/status
```

---

## Monitoring

Run these periodically (or wire them into a cron / dashboard).

```bash
# Bot containers that exited (failed joins leave exited containers):
docker ps -a --filter label=runtime.managed --filter status=exited

# Container-stop work queue depth (should drain to ~0):
docker exec vexa-redis-1 redis-cli XLEN meeting-api:container-stops

# Dead-letter set for container stops that never confirmed (should be empty):
docker exec vexa-redis-1 redis-cli SMEMBERS meeting-api:container-stop-dlq

# Weekly: confirm the cron chain is still alive and re-arming.
ops/schedule-standup.sh list                 # a 'pending' job with a future
                                             # execute_at == chain is alive
ops/schedule-standup.sh show <job_id>        # after first run, confirm
                                             # result.status_code == 201
```

A recurring standup job re-arms ONLY if the previous run completed successfully
AND croniter is present (the runtime-api-cron image provides it). If `list`
shows no future job after a fire time has passed, inspect with `show <job_id>`
and check `result.status_code` (a 4xx means the bot did not actually join) and
the runtime-api logs (`ops/stack.sh logs runtime-api`) for cron re-arm errors.

## Log rotation

The overlay services already rotate logs (json-file, 50m x 3 — see the
`logging:` blocks in `docker-compose.openrouter.yml`). For the CORE services,
set a host-wide default and restart the daemon:

```bash
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{"log-driver":"json-file","log-opts":{"max-size":"50m","max-file":"3"}}
JSON
sudo systemctl restart docker
```

(Restarting the daemon recreates containers; bring the stack back with
`ops/stack.sh up-lean`.)

## Backup

Snapshot these named volumes (e.g. `docker run --rm -v <vol>:/v -v "$PWD":/b
alpine tar czf /b/<vol>.tgz -C /v .`):

- `vexa_postgres-data` — meetings, transcripts, users, tokens (critical)
- `vexa_minio-data` — recordings object store
- `vexa_redis-data` — scheduler jobs + stream offsets (losing this drops
  pending standup schedules; re-run `schedule-standup.sh add`)
- `vexa_recordings-data` — local recording volume
- `vexa_tts-voices` — downloaded Piper voice models (re-downloadable)

## Security

- `ufw allow 22` (SSH) and `ufw allow 8056` (api-gateway) ONLY; `ufw enable`.
- Everything else (postgres 5458, runtime-api 8090, minio 9000/9001, mcp,
  tts) is bound to `127.0.0.1` by the base compose — not internet-reachable.
  The overlay transcriber (8085) and standup-extractor (8086) bind to all
  interfaces by default; keep them behind the firewall (do not `ufw allow`
  them) — they are only called in-network.
- Use random tokens (`openssl rand -hex 24`) for `BOT_API_TOKEN`,
  `ADMIN_TOKEN`, and `TRANSCRIPTION_SERVICE_TOKEN`. `BOT_API_TOKEN` is what
  stops a stranger from scheduling bot joins via runtime-api.

## Troubleshooting

- **Exited bot containers** (`docker ps -a ... status=exited`): inspect logs
  with `docker logs <container>`. Common causes: meeting not started, wrong
  `native_meeting_id`, admission denied.
- **Scheduler job stuck in `failed`** (`schedule-standup.sh show <id>`): the
  scheduler only retries on 5xx/429 and treats 4xx as completed. A `failed`
  status means repeated 5xx from api-gateway (gateway down, or meeting-api/
  runtime-api unhealthy). Check `ops/stack.sh ps` and
  `ops/stack.sh logs api-gateway meeting-api`.
- **Job fired once then never recurred**: croniter re-arm failed. Confirm the
  running runtime-api is the patched image
  (`docker inspect --format '{{.Config.Image}}' vexa-runtime-api-1` should be
  `vexa-openrouter/runtime-api-cron:local`), then check runtime-api logs for
  "Failed to reschedule cron job".
- **Transcriber returns 503**: OpenRouter backpressure / upstream busy. The
  adapter advertises `Retry-After` (`BUSY_RETRY_AFTER_S`) and the bot backs
  off; sustained 503s mean OpenRouter rate-limiting or an invalid
  `OPENROUTER_API_KEY` — check `ops/stack.sh logs transcriber`.
```
