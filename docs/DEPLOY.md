# Vexa Standup — Server Deployment

## 1. Server specs

- Ubuntu 22.04 / 24.04 LTS — **x86_64** (not ARM)
- 4 vCPU · 8 GB RAM · 100 GB SSD
- Public IP, outbound internet
- Inbound: open `22` (SSH). Optional: `8056` (API), `3001` (dashboard)

## 2. GitHub deploy key

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Add the printed key: GitHub → repo **sahildeep1720/vexa** → **Settings → Deploy keys → Add deploy key** (paste, read access). Then:

```bash
ssh -T git@github.com    # expect: "Hi ... You've successfully authenticated"
```

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker compose version
```

## 4. Clone

```bash
git clone git@github.com:sahildeep1720/vexa.git
cd vexa
git checkout feat/openrouter
```

## 5. Configure `.env`

```bash
cp deploy/env-example .env
cat .env.openrouter.example >> .env
{
  echo "TRANSCRIPTION_SERVICE_URL=http://transcriber:8085/v1/audio/transcriptions"
  echo "POST_MEETING_HOOKS=http://standup-extractor:8086/hooks/meeting-completed"
  echo "OPENROUTER_TRANSCRIBE_MODEL=openai/gpt-4o-transcribe"
  echo "OPENROUTER_CHAT_MODEL=openai/gpt-5.5"
  echo "IMAGE_TAG=latest"
  echo "DOCKER_GID=$(getent group docker | cut -d: -f3)"
  echo "TRANSCRIPTION_SERVICE_TOKEN=$(openssl rand -hex 24)"
  echo "INTERNAL_API_SECRET=$(openssl rand -hex 24)"
  echo "ADMIN_TOKEN=$(openssl rand -hex 24)"
  echo "BOT_API_TOKEN=$(openssl rand -hex 24)"
  echo "OPENROUTER_API_KEY=PASTE_YOUR_OPENROUTER_KEY"
} >> .env
nano .env    # set OPENROUTER_API_KEY to your real sk-or-... key
```

## 6. Build & start

```bash
ops/stack.sh build
ops/stack.sh up-lean
make -C deploy/compose init-db
make -C deploy/compose setup-api-key
ops/stack.sh up-lean
```

## 7. Verify

```bash
ops/stack.sh ps
curl -s localhost:8085/health
curl -s localhost:8086/health
curl -s localhost:8090/health
grep '^VEXA_API_KEY=' .env
```

## 8. Daily auto-join (same meeting, every weekday)

```bash
ops/schedule-standup.sh add MEET_CODE --time 10:30 --tz Asia/Kolkata
ops/schedule-standup.sh list
```

- `MEET_CODE` = the `xxx-xxxx-xxx` from `https://meet.google.com/xxx-xxxx-xxx`
- `--time` is local time (24h); `--tz` your timezone; runs Mon–Fri
- Admit **"Vexa"** when it knocks (or enable Quick access in the meeting for no-admit)
- Change schedule: `ops/schedule-standup.sh cancel-meeting MEET_CODE` then `add` again

## Manage

```bash
ops/stack.sh logs                 # tail logs
ops/stack.sh logs transcriber     # one service
ops/stack.sh restart transcriber  # restart one
ops/stack.sh down                 # stop all
```

## Update

```bash
cd vexa && git pull && ops/stack.sh build && ops/stack.sh up-lean
```
