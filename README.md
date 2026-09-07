# AI Video Translator & Dubbing

## Setup

1. Copy `.env.example` to `.env` at the repo root, and fill in:
   - A Supabase project's Postgres connection string, JWT secret, and
     service-role key (Settings → API in the Supabase dashboard).
   - Cloudflare R2 credentials (R2 → Manage API tokens).
   - ElevenLabs, Gemini, and OpenAI API keys.
2. Copy `frontend/.env.local.example` to `frontend/.env.local` and fill in
   the Supabase URL + anon key (same project as above).
3. Run `docker compose up --build`.
4. Frontend: http://localhost:3000 — should show "Backend: ✅ đang hoạt động".
5. Backend health check: http://localhost:8000/health

## Local development without Docker

- Backend: `cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload`
  (requires Python 3.12 — see "Python version" below)
- Frontend: `cd frontend && npm install && npm run dev`
- Redis must be running locally (or point `REDIS_URL` at a remote instance)
  for the Celery worker: `cd backend && celery -A app.core.celery_app worker --loglevel=info`

### Python version

The backend targets Python 3.12 (pinned in `backend/pyproject.toml`) for
compatibility with later phases' ML dependencies (Demucs, faster-whisper).
If your machine's default Python is a different version, use
[uv](https://github.com/astral-sh/uv) to get an isolated 3.12 environment:

```bash
uv python install 3.12
cd backend
uv venv --python 3.12 .venv
uv pip install -e ".[dev]" --python .venv
.venv/Scripts/python.exe -m pytest   # Windows
# .venv/bin/python -m pytest         # macOS/Linux
```

## Tests

- Backend: `cd backend && pytest` (or `.venv/Scripts/python.exe -m pytest` if
  using the uv-managed venv above)
- Frontend: `cd frontend && npm test`
