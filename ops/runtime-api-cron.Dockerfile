# ops/runtime-api-cron.Dockerfile — derived runtime-api image that adds croniter.
#
# THE GAP: services/runtime-api/Dockerfile installs the package with
# `pip install ".[kubernetes]"`. croniter is declared ONLY in the separate
# `[cron]` optional-dependency extra in services/runtime-api/pyproject.toml
# (cron = ["croniter>=2.0"]), so the published vexaai/runtime-api image does
# NOT contain it.
#
# WHY IT MATTERS: runtime_api/scheduler.py re-arms recurring jobs in
# _process_job() — after a completed job it runs `from croniter import croniter`
# to compute the next fire time and re-enqueue. With croniter absent that import
# raises, the surrounding try/except logs "Failed to reschedule cron job" and
# the job is NEVER re-armed. Net effect: a scheduler job carrying metadata.cron
# fires exactly once, then silently stops recurring.
#
# THE FIX: pip-install croniter on top of the published image. No core files
# are touched; this image is wired in via docker-compose.openrouter.yml's
# runtime-api build override. Switch users to root for the install, then drop
# back to the unprivileged `runtime` user the base image already created.

ARG BASE_IMAGE=vexaai/runtime-api:latest
FROM ${BASE_IMAGE}

USER root
RUN pip install --no-cache-dir "croniter>=2.0"
USER runtime
