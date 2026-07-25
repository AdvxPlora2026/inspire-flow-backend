# Implementation Plan

1. Add failing settings tests for the Replicate defaults, optional secret
   normalization, and removal of obsolete local-model settings.
2. Replace SenseVoice engine tests with failing provider-boundary tests for
   language mapping, local validation before network I/O, upload, immediate
   completion, polling completion, output normalization, and safe failures.
3. Implement the minimal Replicate Whisper engine and worker factory rename.
4. Adapt worker/readiness/doctor tests while preserving job idempotency,
   encryption, error mapping, and spool cleanup.
5. Remove the heavy local STT dependency group and refresh `uv.lock` using uv.
6. Update `.env.example`, README, `docs/HANDOFF_STT.md`, broader handoff text,
   and `.trellis/spec/backend/stt-worker.md`.
7. Run focused checks:

   ```bash
   uv run pytest tests/test_config.py tests/workers/test_stt_engine.py \
     tests/workers/test_stt_tasks.py tests/workers/test_stt_doctor.py \
     tests/workers/test_readiness.py tests/workers/test_celery_app.py \
     tests/api/test_transcriptions.py -W error
   ```

8. Run the full quality gate:

   ```bash
   uv lock --check
   uv sync --locked --dev
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest -W error
   ```

## Risk And Rollback Points

- Confirm Hack Club proxies the files endpoint under the documented base path;
  provider calls remain transport-faked in stable tests.
- Keep all secret-bearing values outside fixtures and documentation.
- Do not change the database schema or public endpoint shape; this keeps
  rollback code-only.
- Review upload cleanup behavior so local spool deletion still occurs on every
  terminal path even when remote cleanup is unavailable.
