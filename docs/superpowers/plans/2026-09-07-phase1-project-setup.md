# Phase 1: Project Setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the monorepo skeleton — backend (FastAPI), frontend (Next.js), Docker Compose, Supabase connection, Celery/Redis wiring — with a working end-to-end health check, so every later phase has a place to add code.

**Architecture:** A monorepo with `backend/` (FastAPI + SQLModel + Celery) and `frontend/` (Next.js + TypeScript + Tailwind + shadcn/ui), orchestrated by one `docker-compose.yml` that runs the API, a Celery worker, Redis, and the frontend dev server. The database and auth are Supabase (remote, used in both dev and prod — no local Postgres container).

**Tech Stack:** FastAPI, SQLModel, Alembic, Celery, Redis, pytest, Next.js (App Router), TypeScript, TailwindCSS, shadcn/ui, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- Backend runs Python 3.12 inside Docker regardless of the host's Python version (spec §8).
- Database is PostgreSQL hosted on Supabase for both dev and prod — no local Postgres container (spec §Cơ sở dữ liệu, §3).
- FFmpeg ships inside the backend Docker image; the host does not need it installed (spec §8).
- No dark mode in the frontend (spec §4 tech stack table).
- UI language is Vietnamese only; no i18n framework (spec §2 Ngôn ngữ).
- All third-party keys (Supabase, Redis is self-hosted so no key, ElevenLabs, Gemini, OpenAI, Cloudflare R2) come from `.env`; no in-app key-management UI (spec §2 API Keys/Secrets).
- Repo layout is a monorepo: `frontend/`, `backend/` at the root (spec §7).

## Established Interfaces (produced here, consumed by every later phase)

**Backend (`backend/app/`):**
- `app.core.config.settings` — a `pydantic-settings` singleton with fields: `env: str`, `database_url: str`, `redis_url: str`, `supabase_url: str`, `supabase_jwt_secret: str`, `supabase_service_key: str`, `r2_account_id: str`, `r2_access_key_id: str`, `r2_secret_access_key: str`, `r2_bucket_name: str`, `elevenlabs_api_key: str`, `gemini_api_key: str`, `openai_api_key: str`.
- `app.db.session.engine` — a SQLModel `Engine` built from `settings.database_url`.
- `app.db.session.get_session() -> Generator[Session, None, None]` — FastAPI dependency yielding a `sqlmodel.Session`.
- `app.core.celery_app.celery_app` — a `Celery` instance configured with `settings.redis_url` as broker and backend.
- `app.main.app` — the FastAPI application instance, with `GET /health` returning `{"status": "ok"}`.

**Frontend (`frontend/`):**
- `lib/api.ts` exports `apiFetch(path: string, init?: RequestInit): Promise<Response>` — prefixes `process.env.NEXT_PUBLIC_API_URL`, does not yet attach auth (auth lands in Phase 9).
- `app/page.tsx` — a landing/health page that calls `apiFetch('/health')` and renders the result, proving frontend↔backend wiring.

---

### Task 1: Backend package skeleton + `/health` endpoint

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.main.app` (FastAPI instance), route `GET /health`.

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "video-dubbing-backend"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlmodel>=0.0.22",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "celery[redis]>=5.4",
    "redis>=5.0",
    "pydantic-settings>=2.4",
    "python-jose[cryptography]>=3.3",
    "httpx>=0.27",
    "python-multipart>=0.0.9",
    "boto3>=1.34",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pip install -e ".[dev]" && pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` or `app.main` not found.

- [ ] **Step 4: Write minimal implementation**

```python
# backend/app/__init__.py
```

```python
# backend/app/main.py
from fastapi import FastAPI

app = FastAPI(title="AI Video Dubbing API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

```python
# backend/tests/__init__.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_health.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/__init__.py backend/app/main.py backend/tests/__init__.py backend/tests/test_health.py
git commit -m "feat(backend): scaffold FastAPI app with /health endpoint"
```

---

### Task 2: Settings module (`pydantic-settings`)

**Files:**
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/tests/test_config.py`
- Create: `backend/.env.test` (fixture values used only by tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `app.core.config.settings` (a `Settings` instance) and the `Settings` class itself, with the fields listed in "Established Interfaces" above.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config.py
import os

from app.core.config import Settings


def test_settings_loads_all_required_fields(monkeypatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-service-key")
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_BUCKET_NAME", "bucket")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")

    settings = Settings()

    assert settings.env == "test"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.supabase_url == "https://example.supabase.co"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/core/__init__.py
```

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str
    redis_url: str
    supabase_url: str
    supabase_jwt_secret: str
    supabase_service_key: str
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    elevenlabs_api_key: str
    gemini_api_key: str
    openai_api_key: str


settings = Settings()
```

Note: `pydantic-settings` matches env vars case-insensitively to field names by
default, so `DATABASE_URL` populates `database_url`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_config.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/__init__.py backend/app/core/config.py backend/tests/test_config.py
git commit -m "feat(backend): add pydantic-settings config module"
```

---

### Task 3: Database session module

**Files:**
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/session.py`
- Create: `backend/tests/test_session.py`

**Interfaces:**
- Consumes: `app.core.config.Settings` (Task 2).
- Produces: `app.db.session.get_engine(database_url: str) -> Engine`, `app.db.session.engine` (module-level engine built from `settings.database_url`), `app.db.session.get_session() -> Generator[Session, None, None]`.

- [ ] **Step 1: Write the failing test**

This test builds an engine against a throwaway SQLite file (not Supabase) to
prove the session factory pattern works, without requiring real Supabase
credentials in CI.

```python
# backend/tests/test_session.py
from sqlmodel import Session, SQLModel, text

from app.db.session import get_engine, get_session


def test_get_session_yields_working_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = get_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    session_gen = get_session_override(engine)
    session = next(session_gen)
    try:
        assert isinstance(session, Session)
        result = session.exec(text("SELECT 1")).one()
        assert result[0] == 1
    finally:
        session_gen.close()


def get_session_override(engine):
    """Mirrors get_session's generator shape but takes an explicit engine,
    so the test does not depend on app.core.config.settings.database_url."""
    with Session(engine) as session:
        yield session
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/db/__init__.py
```

```python
# backend/app/db/session.py
from typing import Generator

from sqlmodel import Session, create_engine

from app.core.config import settings


def get_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


engine = get_engine(settings.database_url)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_session.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/__init__.py backend/app/db/session.py backend/tests/test_session.py
git commit -m "feat(backend): add SQLModel session factory"
```

---

### Task 4: Alembic wiring

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/.gitkeep`

**Interfaces:**
- Consumes: `app.db.session.engine`, `app.core.config.settings.database_url`.
- Produces: a working `alembic revision --autogenerate` / `alembic upgrade head` flow. Later phases add model files under `app/models/` and generate migrations against this setup — no code interface, this is tooling.

- [ ] **Step 1: Create `backend/alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handlers]
keys = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatters]
keys = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 2: Create `backend/alembic/env.py`**

```python
from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

from app.core.config import settings

# Import every model module so SQLModel.metadata is fully populated
# before autogenerate compares it against the database.
from app.models import *  # noqa: F401,F403

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import engine_from_config, pool

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create `backend/alembic/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create placeholder for the versions directory**

```bash
mkdir -p backend/alembic/versions
touch backend/alembic/versions/.gitkeep
```

- [ ] **Step 5: Create `app/models/__init__.py` as an empty package (models arrive in later phases)**

```python
# backend/app/models/__init__.py
```

- [ ] **Step 6: Verify Alembic can talk to the config (manual, requires real `.env`)**

Run: `cd backend && cp ../.env.example .env  # fill in real Supabase DATABASE_URL first` then `alembic revision -m "init" --autogenerate`
Expected: A new file appears under `alembic/versions/` with an empty `upgrade()`/`downgrade()` (no models yet). Delete this test revision file before committing — it was only to prove the wiring works; the first real migration is written when Task 9's `Profile`-adjacent models start landing in Phase 9.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic.ini backend/alembic/env.py backend/alembic/script.py.mako backend/alembic/versions/.gitkeep backend/app/models/__init__.py
git commit -m "feat(backend): wire up Alembic migrations"
```

---

### Task 5: Celery app + trivial task

**Files:**
- Create: `backend/app/core/celery_app.py`
- Create: `backend/app/workers/__init__.py`
- Create: `backend/app/workers/ping.py`
- Create: `backend/tests/test_celery_app.py`

**Interfaces:**
- Consumes: `app.core.config.settings.redis_url`.
- Produces: `app.core.celery_app.celery_app` (Celery instance), `app.workers.ping.ping_task` (a task registered on `celery_app`, callable synchronously in tests via `.apply()`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_celery_app.py
from app.core.celery_app import celery_app
from app.workers.ping import ping_task


def test_ping_task_is_registered_on_celery_app():
    assert "app.workers.ping.ping_task" in celery_app.tasks


def test_ping_task_runs_synchronously():
    result = ping_task.apply(args=["hello"])
    assert result.result == "pong: hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_celery_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.celery_app'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/core/celery_app.py
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "video_dubbing",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.ping"],
)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
```

```python
# backend/app/workers/__init__.py
```

```python
# backend/app/workers/ping.py
from app.core.celery_app import celery_app


@celery_app.task(name="app.workers.ping.ping_task")
def ping_task(message: str) -> str:
    return f"pong: {message}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_celery_app.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/celery_app.py backend/app/workers/__init__.py backend/app/workers/ping.py backend/tests/test_celery_app.py
git commit -m "feat(backend): wire up Celery app with a smoke-test task"
```

---

### Task 6: Frontend scaffolding + health page

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next.config.ts`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/app/globals.css`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/page.tsx`
- Create: `frontend/lib/api.ts`
- Create: `frontend/.env.local.example`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/lib/api.test.ts`

**Interfaces:**
- Produces: `lib/api.ts` → `apiFetch(path: string, init?: RequestInit): Promise<Response>`; `app/page.tsx` renders backend health status.

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "video-dubbing-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run"
  },
  "dependencies": {
    "next": "15.5.0",
    "react": "19.1.0",
    "react-dom": "19.1.0",
    "@supabase/supabase-js": "2.45.4"
  },
  "devDependencies": {
    "typescript": "5.6.3",
    "@types/node": "22.7.4",
    "@types/react": "19.0.0",
    "@types/react-dom": "19.0.0",
    "tailwindcss": "3.4.13",
    "postcss": "8.4.47",
    "autoprefixer": "10.4.20",
    "vitest": "2.1.2"
  }
}
```

- [ ] **Step 2: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "paths": { "@/*": ["./*"] }
  },
  "include": ["**/*.ts", "**/*.tsx", "next-env.d.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Write the failing test for `apiFetch`**

```typescript
// frontend/lib/api.test.ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { apiFetch } from "./api";

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000");
  });

  it("prefixes the configured API base URL", async () => {
    await apiFetch("/health");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/health",
      undefined
    );
  });
});
```

- [ ] **Step 4: Create `frontend/vitest.config.ts`**

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
  },
});
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — `frontend/lib/api.ts` does not exist yet.

- [ ] **Step 6: Write minimal implementation**

```typescript
// frontend/lib/api.ts
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return fetch(`${base}${path}`, init);
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (1 passed)

- [ ] **Step 8: Add Next.js app shell (Tailwind, layout, health page)**

```typescript
// frontend/next.config.ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {};

export default nextConfig;
```

```typescript
// frontend/tailwind.config.ts
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};

export default config;
```

```javascript
// frontend/postcss.config.mjs
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

```css
/* frontend/app/globals.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

```typescript
// frontend/app/layout.tsx
import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "AI Dịch & Lồng tiếng Video" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
```

```typescript
// frontend/app/page.tsx
import { apiFetch } from "@/lib/api";

async function getHealth(): Promise<{ status: string } | null> {
  try {
    const res = await apiFetch("/health");
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export default async function HomePage() {
  const health = await getHealth();
  return (
    <main className="flex min-h-screen items-center justify-center">
      <p>
        Backend:{" "}
        {health?.status === "ok" ? "✅ đang hoạt động" : "❌ không kết nối được"}
      </p>
    </main>
  );
}
```

- [ ] **Step 9: Create `frontend/.env.local.example`**

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- [ ] **Step 10: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): scaffold Next.js app with health check page"
```

---

### Task 7: Root `.env.example` and README

**Files:**
- Create: `.env.example`
- Create: `README.md`

**Interfaces:** none (documentation/config only).

- [ ] **Step 1: Create `.env.example`**

```bash
# --- Shared ---
ENV=development

# --- Database (Supabase Postgres, used for BOTH dev and prod) ---
DATABASE_URL=postgresql+psycopg://postgres:password@db.xxxxx.supabase.co:5432/postgres
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_JWT_SECRET=replace-with-supabase-project-jwt-secret
SUPABASE_SERVICE_KEY=replace-with-supabase-service-role-key

# --- Redis (local via docker-compose in dev; Railway-managed in prod) ---
REDIS_URL=redis://redis:6379/0

# --- Cloudflare R2 ---
R2_ACCOUNT_ID=replace-me
R2_ACCESS_KEY_ID=replace-me
R2_SECRET_ACCESS_KEY=replace-me
R2_BUCKET_NAME=video-dubbing

# --- Third-party AI APIs ---
ELEVENLABS_API_KEY=replace-me
GEMINI_API_KEY=replace-me
OPENAI_API_KEY=replace-me

# --- Frontend ---
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://xxxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=replace-with-supabase-anon-key
```

- [ ] **Step 2: Create `README.md`**

```markdown
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
- Frontend: `cd frontend && npm install && npm run dev`
- Redis must be running locally (or point `REDIS_URL` at a remote instance)
  for the Celery worker: `cd backend && celery -A app.core.celery_app worker --loglevel=info`

## Tests

- Backend: `cd backend && pytest`
- Frontend: `cd frontend && npm test`
```

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "docs: add root .env.example and setup README"
```

---

### Task 8: Dockerfiles + docker-compose.yml

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `docker-compose.yml`

**Interfaces:** none (infra only). Consumes every service defined in Tasks 1–7.

- [ ] **Step 1: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `frontend/Dockerfile`**

```dockerfile
FROM node:22-slim

WORKDIR /app

COPY package.json .
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379/0
    volumes:
      - ./backend:/app
    ports:
      - "8000:8000"
    depends_on:
      - redis

  worker:
    build: ./backend
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379/0
    volumes:
      - ./backend:/app
    command: celery -A app.core.celery_app worker --loglevel=info
    depends_on:
      - redis

  frontend:
    build: ./frontend
    env_file: frontend/.env.local
    volumes:
      - ./frontend:/app
      - /app/node_modules
    ports:
      - "3000:3000"
    depends_on:
      - backend
```

- [ ] **Step 4: Verify the stack boots (manual, requires a filled-in `.env`)**

Run: `docker compose up --build`
Expected: `backend` logs `Uvicorn running on http://0.0.0.0:8000`, `worker` logs `celery@... ready`, `frontend` logs `Ready in ...ms`. Visiting http://localhost:3000 shows "Backend: ✅ đang hoạt động".

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile frontend/Dockerfile docker-compose.yml
git commit -m "feat: add Dockerfiles and docker-compose for full local stack"
```

---

## Definition of Done for Phase 1

- [ ] `cd backend && pytest` passes (health, config, session, celery tests).
- [ ] `cd frontend && npm test` passes (api.ts test).
- [ ] `docker compose up --build` boots all four services with a real `.env`.
- [ ] http://localhost:3000 shows the backend as reachable.
- [ ] Report back to the user with what was built, test output, and any deviations before starting Phase 2.
