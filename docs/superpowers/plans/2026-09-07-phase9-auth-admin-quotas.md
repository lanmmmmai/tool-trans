# Phase 9: Auth, Admin, Quotas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dev auth stub with real Supabase JWT verification and just-in-time user profiles, add admin-only user/quota management and a usage-cost overview, retrofit the pipeline workers to log API usage, and build the Settings and Admin screens.

**Architecture:** A `Profile` model backing Supabase Auth users, created just-in-time on first authenticated request; `get_current_user_id` (used unchanged by every router since Phase 2) is upgraded from a constant-returning stub to a real JWT-verifying dependency — its signature to callers never changes, so no other phase's code needs to be touched for that swap; a `Quota` model and admin endpoints; a `UsageLog` model with a small logging helper called from the transcribe/translate/dub workers; Login/Register pages using the Supabase JS client; Settings and Admin frontend pages.

**Tech Stack:** FastAPI, `python-jose` (JWT verification), Supabase Auth (`@supabase/supabase-js` on the frontend), SQLModel, Next.js.

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- Full registration/login via Supabase Auth; roles `user` and `admin`; admins can view all users and set a per-user monthly minutes quota manually — no fixed formula (spec §Người dùng & Quyền truy cập, §Hạn mức & Theo dõi chi phí).
- The backend verifies the Supabase-issued JWT on every request; it does not implement its own signup/login flow — that lives entirely in Supabase, called from the frontend (spec §Cơ sở dữ liệu, §Kiến trúc).
- Every external API call (STT/translation/TTS) is logged with provider, operation, cost, and unit count, tied to user and project, for **visibility only** — no automatic hard-stop enforcement beyond what an admin manually sets (spec §Hạn mức & Theo dõi chi phí). The cost figures logged here are rough, documented estimates, not billing-grade accounting.
- No in-app API-key management UI — keys stay in `.env` (spec §API Keys/Secrets, discovery Q74-A). This phase does not add one.
- `Project.user_id` and `GlossaryTerm.user_id` were stored since Phase 2/5 as plain strings with no foreign key (documented then as deliberate, deferred to this phase). This phase adds the `profiles` table and backfills those foreign keys.

## Established Interfaces (produced here; nothing further consumes them within this spec's scope)

- `app.models.profile.Profile` — SQLModel table (fields per spec §5): `id` (matches the Supabase `auth.users` UUID), `email`, `role`, `created_at`.
- `app.models.quota.Quota`, `app.models.usage_log.UsageLog` — SQLModel tables (fields per spec §5).
- `app.core.auth.AuthUser(id: str, email: str, role: str)`, `app.core.auth.get_current_user(...) -> AuthUser`, `app.core.auth.get_current_user_id(...) -> str` (same name/return type every prior phase already depends on — only its internals change), `app.core.auth.require_admin(...) -> AuthUser`.
- `app.services.usage.log_usage(session, user_id, project_id, api_provider, operation, cost_usd, units) -> None`.
- `frontend/lib/supabase.ts` — exports `supabase` (browser Supabase client).
- `frontend/lib/api.ts`'s `apiFetch` — upgraded to attach `Authorization: Bearer <supabase access token>` to every request.

---

### Task 1: `Profile` model + migration

**Files:**
- Create: `backend/app/models/profile.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_profile_model.py`

**Interfaces:**
- Produces: `Profile` SQLModel class.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_profile_model.py
from sqlmodel import Session, SQLModel, create_engine

from app.models.profile import Profile


def test_create_profile_with_default_role():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        profile = Profile(id="user-uuid-1", email="a@example.com")
        session.add(profile)
        session.commit()
        session.refresh(profile)
        assert profile.role == "user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_profile_model.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/profile.py
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"

    id: str = Field(primary_key=True)  # matches Supabase auth.users.id
    email: str
    role: str = Field(default="user")  # "user" | "admin"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

```python
# backend/app/models/__init__.py
from app.models.dubbed_segment import DubbedSegment  # noqa: F401
from app.models.export import Export  # noqa: F401
from app.models.glossary_term import GlossaryTerm  # noqa: F401
from app.models.job import Job  # noqa: F401
from app.models.profile import Profile  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.transcript_segment import TranscriptSegment  # noqa: F401
from app.models.translation_segment import TranslationSegment  # noqa: F401
from app.models.video import Video  # noqa: F401
from app.models.voice import Voice  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_profile_model.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Generate migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add profiles table" --autogenerate && alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/profile.py backend/app/models/__init__.py backend/tests/test_profile_model.py backend/alembic/versions/
git commit -m "feat(backend): add Profile model + migration"
```

---

### Task 2: Real Supabase JWT auth with JIT profile provisioning

**Files:**
- Modify: `backend/app/core/auth.py`
- Create: `backend/tests/test_auth_jwt.py`

**Interfaces:**
- Produces: `AuthUser`, `get_current_user(credentials, session) -> AuthUser`, `get_current_user_id(user: AuthUser = Depends(get_current_user)) -> str`, `require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_auth_jwt.py
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlmodel import Session, SQLModel, create_engine

from app.core.auth import get_current_user_id, require_admin
from app.core.config import settings
from app.db.session import get_session
from app.models.profile import Profile

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


app = FastAPI()
app.dependency_overrides[get_session] = override_get_session


@app.get("/whoami")
def whoami(user_id: str = __import__("fastapi").Depends(get_current_user_id)):
    return {"user_id": user_id}


@app.get("/admin-only")
def admin_only(user=__import__("fastapi").Depends(require_admin)):
    return {"ok": True}


client = TestClient(app)


def make_token(sub: str, email: str = "a@example.com", expired: bool = False) -> str:
    exp = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=1))
    payload = {"sub": sub, "email": email, "aud": "authenticated", "exp": exp}
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")


def test_valid_token_creates_profile_and_returns_user_id():
    token = make_token("user-abc")
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "user-abc"

    with Session(engine) as session:
        profile = session.get(Profile, "user-abc")
        assert profile is not None
        assert profile.email == "a@example.com"
        assert profile.role == "user"


def test_missing_token_returns_401():
    resp = client.get("/whoami")
    assert resp.status_code in (401, 403)  # HTTPBearer returns 403 by default when missing


def test_expired_token_returns_401():
    token = make_token("user-xyz", expired=True)
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_require_admin_rejects_non_admin():
    token = make_token("user-not-admin")
    resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_require_admin_allows_admin():
    with Session(engine) as session:
        session.add(Profile(id="admin-1", email="admin@example.com", role="admin"))
        session.commit()

    token = make_token("admin-1", email="admin@example.com")
    resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_auth_jwt.py -v`
Expected: FAIL — `get_current_user_id` is still the constant-returning stub; `require_admin` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/core/auth.py
"""Supabase JWT verification. Every router since Phase 2 already depends on
`get_current_user_id` by name — this file changes only what happens inside
it, not its name or return type, so no other file needs to change."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel
from sqlmodel import Session

from app.core.config import settings
from app.db.session import get_session

security = HTTPBearer()


class AuthUser(BaseModel):
    id: str
    email: str
    role: str


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_session),
) -> AuthUser:
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = payload.get("sub")
    email = payload.get("email", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")

    # Local import to avoid a circular import between app.core.auth and
    # app.models at module load time.
    from app.models.profile import Profile

    profile = session.get(Profile, user_id)
    if profile is None:
        profile = Profile(id=user_id, email=email)
        session.add(profile)
        session.commit()
        session.refresh(profile)

    return AuthUser(id=profile.id, email=profile.email, role=profile.role)


def get_current_user_id(user: AuthUser = Depends(get_current_user)) -> str:
    return user.id


def require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_auth_jwt.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full backend suite — every existing router's tests must still pass unchanged**

Run: `cd backend && pytest -v`
Expected: every test file from Phases 1-8 that overrides `get_current_user_id` via `app.dependency_overrides` (all of them do, or use the default stub's fixed user id) either already overrides `get_current_user_id`/`get_session` or now needs one. Since prior test files call the API directly with `TestClient(app)` without overriding `get_current_user_id`, and `get_current_user_id` now requires a real bearer token, those tests will start failing. Fix this by overriding the dependency in each existing test file, the same way `get_session` is already overridden. Add to every existing test file that calls protected endpoints (`test_projects_api.py`, `test_upload_api.py`, `test_transcript_api.py`, `test_transcript_patch_api.py`, `test_translation_api.py`, `test_glossary_api.py`, `test_project_voices_api.py`, `test_dub_api.py`, `test_export_api.py`, `test_regenerate_api.py`, `test_voices_catalog_api.py` if it uses auth):

```python
# add near the top of each such test file, alongside the existing
# app.dependency_overrides[get_session] = override_get_session line
from app.core.auth import get_current_user_id

app.dependency_overrides[get_current_user_id] = lambda: "00000000-0000-0000-0000-000000000001"
```

This keeps every prior phase's test suite green while now exercising the
real dependency-injection path (a test-supplied override), which is the
normal, intended way to unit-test FastAPI routes that depend on auth.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/auth.py backend/tests/test_auth_jwt.py backend/tests/test_projects_api.py backend/tests/test_upload_api.py backend/tests/test_transcript_api.py backend/tests/test_transcript_patch_api.py backend/tests/test_translation_api.py backend/tests/test_glossary_api.py backend/tests/test_project_voices_api.py backend/tests/test_dub_api.py backend/tests/test_export_api.py backend/tests/test_regenerate_api.py
git commit -m "feat(backend): replace dev auth stub with real Supabase JWT verification"
```

---

### Task 3: Backfill foreign keys on `Project.user_id` and `GlossaryTerm.user_id`

**Files:**
- Modify: `backend/app/models/project.py`
- Modify: `backend/app/models/glossary_term.py`

**Interfaces:** none new — tightens existing columns.

- [ ] **Step 1: Add the foreign key declarations**

```python
# backend/app/models/project.py  (change the user_id field)
    user_id: str = Field(foreign_key="profiles.id", index=True)
```

```python
# backend/app/models/glossary_term.py  (change the user_id field)
    user_id: str = Field(foreign_key="profiles.id", index=True)
```

- [ ] **Step 2: Generate the migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add fk from projects and glossary_terms to profiles" --autogenerate`

Before running `alembic upgrade head`, open the generated migration file and,
if this database already has `projects`/`glossary_terms` rows created under
the Phase 2-8 dev stub user (`00000000-0000-0000-0000-000000000001`), add a
data migration line before the `ALTER TABLE ... ADD CONSTRAINT` so those
rows don't violate the new constraint:

```python
def upgrade() -> None:
    op.execute(
        "INSERT INTO profiles (id, email, role, created_at) "
        "VALUES ('00000000-0000-0000-0000-000000000001', 'dev@localhost', 'user', now()) "
        "ON CONFLICT (id) DO NOTHING"
    )
    # ... the autogenerated create_foreign_key(...) calls follow here
```

Run: `alembic upgrade head`

- [ ] **Step 3: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all tests still pass (SQLite in-memory tests don't enforce FKs by
default, so this change is invisible to the unit test suite — it only
matters against the real Postgres/Supabase database).

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/project.py backend/app/models/glossary_term.py backend/alembic/versions/
git commit -m "feat(backend): backfill foreign keys from projects/glossary_terms to profiles"
```

---

### Task 4: `Quota` model + admin quota endpoints

**Files:**
- Create: `backend/app/models/quota.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/api/admin.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_quota_model.py`
- Create: `backend/tests/test_admin_api.py`

**Interfaces:**
- Produces: `Quota` SQLModel class; `GET /api/admin/users`, `PATCH /api/admin/users/{id}/quota`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_quota_model.py
from sqlmodel import Session, SQLModel, create_engine

from app.models.profile import Profile
from app.models.quota import Quota


def test_create_quota():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Profile(id="u1", email="a@example.com"))
        session.commit()

        quota = Quota(user_id="u1", minutes_limit_per_month=120, set_by_admin_id="admin-1")
        session.add(quota)
        session.commit()
        session.refresh(quota)
        assert quota.id is not None
```

```python
# backend/tests/test_admin_api.py
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.core.auth import get_current_user, get_current_user_id
from app.db.session import get_session
from app.main import app
from app.models.profile import Profile

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


def seed_users():
    with Session(engine) as session:
        session.add(Profile(id="admin-1", email="admin@example.com", role="admin"))
        session.add(Profile(id="user-1", email="user1@example.com", role="user"))
        session.commit()


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)


def as_admin():
    from app.core.auth import AuthUser

    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id="admin-1", email="admin@example.com", role="admin"
    )
    app.dependency_overrides[get_current_user_id] = lambda: "admin-1"


def as_regular_user():
    from app.core.auth import AuthUser

    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id="user-1", email="user1@example.com", role="user"
    )
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"


def test_list_users_requires_admin():
    seed_users()
    as_regular_user()
    resp = client.get("/api/admin/users")
    assert resp.status_code == 403


def test_admin_can_list_users_and_set_quota():
    seed_users()
    as_admin()

    list_resp = client.get("/api/admin/users")
    assert list_resp.status_code == 200
    emails = {u["email"] for u in list_resp.json()}
    assert "user1@example.com" in emails

    quota_resp = client.patch(
        "/api/admin/users/user-1/quota", json={"minutes_limit_per_month": 200}
    )
    assert quota_resp.status_code == 200
    assert quota_resp.json()["minutes_limit_per_month"] == 200

    # Re-listing should now show the updated quota.
    list_resp2 = client.get("/api/admin/users")
    user1 = next(u for u in list_resp2.json() if u["email"] == "user1@example.com")
    assert user1["quota_minutes_limit_per_month"] == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_quota_model.py tests/test_admin_api.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/quota.py
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Quota(SQLModel, table=True):
    __tablename__ = "quotas"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="profiles.id", unique=True, index=True)
    minutes_limit_per_month: int
    set_by_admin_id: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

```python
# backend/app/models/__init__.py  (add this import alongside the others)
from app.models.quota import Quota  # noqa: F401
```

```python
# backend/app/api/admin.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import AuthUser, require_admin
from app.db.session import get_session
from app.models.profile import Profile
from app.models.quota import Quota

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserWithQuotaRead(BaseModel):
    id: str
    email: str
    role: str
    quota_minutes_limit_per_month: int | None


class SetQuotaRequest(BaseModel):
    minutes_limit_per_month: int


class QuotaRead(BaseModel):
    id: str
    user_id: str
    minutes_limit_per_month: int
    set_by_admin_id: str | None


@router.get("/users", response_model=list[UserWithQuotaRead])
def list_users(
    session: Session = Depends(get_session),
    _admin: AuthUser = Depends(require_admin),
):
    profiles = session.exec(select(Profile)).all()
    quotas_by_user = {
        q.user_id: q for q in session.exec(select(Quota)).all()
    }

    return [
        UserWithQuotaRead(
            id=p.id,
            email=p.email,
            role=p.role,
            quota_minutes_limit_per_month=(
                quotas_by_user[p.id].minutes_limit_per_month if p.id in quotas_by_user else None
            ),
        )
        for p in profiles
    ]


@router.patch("/users/{user_id}/quota", response_model=QuotaRead)
def set_user_quota(
    user_id: str,
    payload: SetQuotaRequest,
    session: Session = Depends(get_session),
    admin: AuthUser = Depends(require_admin),
):
    quota = session.exec(select(Quota).where(Quota.user_id == user_id)).first()
    if quota is None:
        quota = Quota(user_id=user_id, minutes_limit_per_month=payload.minutes_limit_per_month, set_by_admin_id=admin.id)
    else:
        quota.minutes_limit_per_month = payload.minutes_limit_per_month
        quota.set_by_admin_id = admin.id
        quota.updated_at = datetime.now(timezone.utc)

    session.add(quota)
    session.commit()
    session.refresh(quota)
    return quota
```

```python
# backend/app/main.py  (add to existing file)
from app.api.admin import router as admin_router

app.include_router(admin_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_quota_model.py tests/test_admin_api.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Generate migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add quotas table" --autogenerate && alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/quota.py backend/app/models/__init__.py backend/app/api/admin.py backend/app/main.py backend/tests/test_quota_model.py backend/tests/test_admin_api.py backend/alembic/versions/
git commit -m "feat(backend): add Quota model and admin user/quota endpoints"
```

---

### Task 5: `UsageLog` model + `log_usage` helper + worker retrofits

**Files:**
- Create: `backend/app/models/usage_log.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/usage.py`
- Modify: `backend/app/workers/transcribe.py`
- Modify: `backend/app/workers/translate.py`
- Modify: `backend/app/workers/dub.py`
- Create: `backend/tests/test_usage_log.py`
- Modify: `backend/tests/test_transcribe_task.py`
- Modify: `backend/tests/test_translate_task.py`
- Modify: `backend/tests/test_dub_task.py`

**Interfaces:**
- Produces: `UsageLog` SQLModel class; `app.services.usage.log_usage(session, user_id, project_id, api_provider, operation, cost_usd, units) -> None`.

- [ ] **Step 1: Write the failing test for the model and helper**

```python
# backend/tests/test_usage_log.py
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.profile import Profile
from app.models.project import Project
from app.models.usage_log import UsageLog
from app.services.usage import log_usage


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_log_usage_writes_a_row():
    engine = make_engine()
    with Session(engine) as session:
        session.add(Profile(id="u1", email="a@example.com"))
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="silent"
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        log_usage(
            session, user_id="u1", project_id=project.id,
            api_provider="elevenlabs", operation="stt", cost_usd=0.05, units=13.6,
        )

        row = session.exec(select(UsageLog)).one()
        assert row.api_provider == "elevenlabs"
        assert row.cost_usd == 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_usage_log.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/usage_log.py
from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


class UsageLog(SQLModel, table=True):
    __tablename__ = "usage_logs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="profiles.id", index=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    api_provider: str
    operation: str
    cost_usd: float
    units: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

```python
# backend/app/models/__init__.py  (add alongside the others)
from app.models.usage_log import UsageLog  # noqa: F401
```

```python
# backend/app/services/usage.py
from sqlmodel import Session

from app.models.usage_log import UsageLog


def log_usage(
    session: Session,
    user_id: str,
    project_id: str,
    api_provider: str,
    operation: str,
    cost_usd: float,
    units: float,
) -> None:
    session.add(
        UsageLog(
            user_id=user_id,
            project_id=project_id,
            api_provider=api_provider,
            operation=operation,
            cost_usd=cost_usd,
            units=units,
        )
    )
    session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_usage_log.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Retrofit `transcribe_task`**

```python
# backend/app/workers/transcribe.py  (add import and one call)
from app.models.project import Project
from app.services.usage import log_usage

ELEVENLABS_COST_PER_HOUR_USD = 0.22

# ... inside the try block, right after `stt_segments, engine_used = transcribe_with_fallback(audio_path)`:
            if engine_used == "elevenlabs":
                project_row = session.get(Project, project_id)
                cost = (video.duration_sec / 3600) * ELEVENLABS_COST_PER_HOUR_USD
                log_usage(
                    session, user_id=project_row.user_id, project_id=project_id,
                    api_provider="elevenlabs", operation="stt",
                    cost_usd=cost, units=video.duration_sec,
                )
```

- [ ] **Step 6: Retrofit `translate_task`**

```python
# backend/app/workers/translate.py  (add import and one call per chunk)
from app.services.usage import log_usage

GEMINI_COST_PER_1K_CHARS_USD = 0.0003
OPENAI_COST_PER_1K_CHARS_USD = 0.0006

# ... inside the chunk loop, right after `translations = translator.translate_chunk(...)`:
            chars_translated = sum(len(s.text) for s in chunk_segments_for_prompt)
            rate = OPENAI_COST_PER_1K_CHARS_USD if engine_name == "openai" else GEMINI_COST_PER_1K_CHARS_USD
            log_usage(
                session, user_id=project.user_id, project_id=project_id,
                api_provider=engine_name, operation="translate",
                cost_usd=(chars_translated / 1000) * rate, units=chars_translated,
            )
```

- [ ] **Step 7: Retrofit `dub_task`**

```python
# backend/app/workers/dub.py  (add import and one call per segment)
from app.services.usage import log_usage
from app.models.project import Project

GEMINI_TTS_COST_PER_1K_CHARS_USD = 0.0015

# ... inside the per-segment loop, right after the DubbedSegment is committed:
                if voice.engine == "gemini_tts":
                    project_row = session.get(Project, project_id)
                    text_len = len(_effective_translated_text(translation))
                    log_usage(
                        session, user_id=project_row.user_id, project_id=project_id,
                        api_provider="gemini_tts", operation="tts",
                        cost_usd=(text_len / 1000) * GEMINI_TTS_COST_PER_1K_CHARS_USD,
                        units=text_len,
                    )
                # edge-tts is free — no usage cost to log, but you may still
                # want units logged for volume visibility; omitted here to
                # keep the log focused on paid usage.
```

- [ ] **Step 8: Update the three workers' existing tests to seed a `Profile` row (needed now that `UsageLog.user_id` has a real FK target) and assert a `UsageLog` row was written**

```python
# backend/tests/test_transcribe_task.py  (add to seed_project_with_video)
from app.models.profile import Profile
from app.models.usage_log import UsageLog

def seed_project_with_video(session):
    session.add(Profile(id="u1", email="a@example.com"))
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
    )
    # ... rest unchanged, but user_id="u1" instead of the previous placeholder if different
```

Add this assertion to `test_transcribe_task_writes_segments_and_marks_job_done`:

```python
    with Session(engine) as session:
        usage_rows = session.exec(select(UsageLog)).all()
        assert len(usage_rows) == 1
        assert usage_rows[0].api_provider == "elevenlabs"
```

Apply the equivalent seed-a-`Profile` + assert-a-`UsageLog`-row pattern to
`test_translate_task.py` (asserting `api_provider == "gemini"`, since that
test's fixture uses the Gemini engine) and `test_dub_task.py`'s
success-path test (this one asserts **no** `UsageLog` row for the edge-tts
success case, since edge-tts is free and Step 7 above only logs
`gemini_tts` usage).

- [ ] **Step 9: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-9 tests pass.

- [ ] **Step 10: Commit**

```bash
git add backend/app/models/usage_log.py backend/app/models/__init__.py backend/app/services/usage.py backend/app/workers/transcribe.py backend/app/workers/translate.py backend/app/workers/dub.py backend/tests/test_usage_log.py backend/tests/test_transcribe_task.py backend/tests/test_translate_task.py backend/tests/test_dub_task.py
git commit -m "feat(backend): add UsageLog model and retrofit workers to log API cost/usage"
```

---

### Task 6: `GET /api/admin/usage` overview endpoint

**Files:**
- Modify: `backend/app/api/admin.py`
- Create: `backend/tests/test_admin_usage_api.py`

**Interfaces:**
- Produces: `GET /api/admin/usage` — `list[{"user_id": str, "email": str, "total_cost_usd": float, "total_units": float}]`, aggregated across all `usage_logs`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_usage_api.py
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.core.auth import get_current_user, get_current_user_id, AuthUser
from app.db.session import get_session
from app.main import app
from app.models.profile import Profile
from app.models.project import Project
from app.models.usage_log import UsageLog

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session
app.dependency_overrides[get_current_user] = lambda: AuthUser(id="admin-1", email="admin@example.com", role="admin")
app.dependency_overrides[get_current_user_id] = lambda: "admin-1"
client = TestClient(app)


def test_admin_usage_overview_aggregates_by_user():
    with Session(engine) as session:
        session.add(Profile(id="admin-1", email="admin@example.com", role="admin"))
        session.add(Profile(id="user-1", email="user1@example.com"))
        project = Project(
            user_id="user-1", title="t", source_language="en", target_language="vi", audio_mode="silent"
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        session.add(UsageLog(user_id="user-1", project_id=project.id, api_provider="elevenlabs", operation="stt", cost_usd=0.10, units=10))
        session.add(UsageLog(user_id="user-1", project_id=project.id, api_provider="gemini", operation="translate", cost_usd=0.02, units=500))
        session.commit()

    resp = client.get("/api/admin/usage")
    assert resp.status_code == 200
    body = resp.json()
    row = next(r for r in body if r["user_id"] == "user-1")
    assert round(row["total_cost_usd"], 2) == 0.12
    assert row["email"] == "user1@example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_admin_usage_api.py -v`
Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/admin.py  (append)
from sqlmodel import func

from app.models.usage_log import UsageLog


class UsageOverviewRow(BaseModel):
    user_id: str
    email: str
    total_cost_usd: float
    total_units: float


@router.get("/usage", response_model=list[UsageOverviewRow])
def get_usage_overview(
    session: Session = Depends(get_session),
    _admin: AuthUser = Depends(require_admin),
):
    rows = session.exec(
        select(
            UsageLog.user_id,
            func.sum(UsageLog.cost_usd),
            func.sum(UsageLog.units),
        ).group_by(UsageLog.user_id)
    ).all()

    profiles_by_id = {p.id: p for p in session.exec(select(Profile)).all()}

    return [
        UsageOverviewRow(
            user_id=user_id,
            email=profiles_by_id[user_id].email if user_id in profiles_by_id else "unknown",
            total_cost_usd=total_cost or 0.0,
            total_units=total_units or 0.0,
        )
        for user_id, total_cost, total_units in rows
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_admin_usage_api.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/admin.py backend/tests/test_admin_usage_api.py
git commit -m "feat(backend): add admin usage/cost overview endpoint"
```

---

### Task 7: Frontend — Supabase client, authenticated `apiFetch`, Login/Register

**Files:**
- Create: `frontend/lib/supabase.ts`
- Modify: `frontend/lib/api.ts`
- Create: `frontend/app/login/page.tsx`
- Create: `frontend/app/register/page.tsx`
- Modify: `frontend/lib/api.test.ts`
- Modify: `frontend/package.json` (already has `@supabase/supabase-js` from Phase 1)

**Interfaces:**
- Produces: `lib/supabase.ts` exports `supabase`; `apiFetch` now attaches the current session's access token.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/lib/api.test.ts  (add a new describe block)
import { vi, describe, expect, it, beforeEach } from "vitest";

describe("apiFetch with auth", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000");
  });

  it("attaches the Supabase access token as a Bearer header when a session exists", async () => {
    vi.doMock("./supabase", () => ({
      supabase: {
        auth: {
          getSession: vi.fn(async () => ({
            data: { session: { access_token: "test-token-123" } },
          })),
        },
      },
    }));

    const { apiFetch } = await import("./api");
    await apiFetch("/api/projects");

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer test-token-123" }),
      })
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `apiFetch` doesn't attach auth yet.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/lib/supabase.ts
import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
```

```typescript
// frontend/lib/api.ts  (replace the existing apiFetch definition at the top of the file)
import { supabase } from "./supabase";

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;

  const headers = new Headers(init?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return fetch(`${base}${path}`, { ...init, headers });
}
```

Note: this changes the request shape from `undefined` headers (Phase 1's
original test) to always passing a `Headers` object. Update Phase 1's
original health-check test expectation accordingly:

```typescript
// frontend/lib/api.test.ts  (fix the original "prefixes the configured API base URL" test)
it("prefixes the configured API base URL", async () => {
  vi.doMock("./supabase", () => ({
    supabase: { auth: { getSession: vi.fn(async () => ({ data: { session: null } })) } },
  }));
  const { apiFetch } = await import("./api");
  await apiFetch("/health");
  expect(fetch).toHaveBeenCalledWith("http://localhost:8000/health", expect.anything());
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Build Login and Register pages**

```typescript
// frontend/app/login/page.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
    if (signInError) {
      setError(signInError.message);
      return;
    }
    router.push("/dashboard");
  }

  return (
    <main className="mx-auto max-w-sm p-8">
      <h1 className="mb-6 text-2xl font-semibold">Đăng nhập</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <input
          type="email"
          placeholder="Email"
          className="w-full rounded border p-2"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          type="password"
          placeholder="Mật khẩu"
          className="w-full rounded border p-2"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button type="submit" className="w-full rounded bg-blue-600 py-2 text-white">
          Đăng nhập
        </button>
      </form>
      <p className="mt-4 text-sm text-gray-500">
        Chưa có tài khoản? <Link href="/register" className="text-blue-600">Đăng ký</Link>
      </p>
    </main>
  );
}
```

```typescript
// frontend/app/register/page.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { supabase } from "@/lib/supabase";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const { error: signUpError } = await supabase.auth.signUp({ email, password });
    if (signUpError) {
      setError(signUpError.message);
      return;
    }
    setInfo("Kiểm tra email để xác nhận tài khoản, sau đó đăng nhập.");
    setTimeout(() => router.push("/login"), 2000);
  }

  return (
    <main className="mx-auto max-w-sm p-8">
      <h1 className="mb-6 text-2xl font-semibold">Đăng ký</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <input
          type="email"
          placeholder="Email"
          className="w-full rounded border p-2"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          type="password"
          placeholder="Mật khẩu"
          className="w-full rounded border p-2"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={6}
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        {info && <p className="text-sm text-green-600">{info}</p>}
        <button type="submit" className="w-full rounded bg-blue-600 py-2 text-white">
          Đăng ký
        </button>
      </form>
      <p className="mt-4 text-sm text-gray-500">
        Đã có tài khoản? <Link href="/login" className="text-blue-600">Đăng nhập</Link>
      </p>
    </main>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/supabase.ts frontend/lib/api.ts frontend/app/login/ frontend/app/register/ frontend/lib/api.test.ts
git commit -m "feat(frontend): add Supabase auth, authenticated apiFetch, Login/Register pages"
```

---

### Task 8: Frontend — Settings page (global glossary + default voice)

**Files:**
- Create: `frontend/app/settings/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/app/projects/[id]/voices/page.tsx`

**Interfaces:**
- Produces: `lib/api.ts` exports `getGlossaryTerms()`, `createGlossaryTerm(sourceTerm, targetTerm)`.

- [ ] **Step 1: Add API functions (no new test — thin wrappers over the already-tested Phase 5 glossary endpoints; covered by the Settings page's manual verification)**

```typescript
// frontend/lib/types.ts  (append)
export interface GlossaryTerm {
  id: string;
  source_term: string;
  target_term: string;
}
```

```typescript
// frontend/lib/api.ts  (append)
import type { GlossaryTerm } from "./types";

export async function getGlossaryTerms(): Promise<GlossaryTerm[]> {
  const res = await apiFetch("/api/glossary");
  if (!res.ok) throw new Error("Failed to load glossary");
  return res.json();
}

export async function createGlossaryTerm(
  sourceTerm: string,
  targetTerm: string
): Promise<GlossaryTerm> {
  const res = await apiFetch("/api/glossary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_term: sourceTerm, target_term: targetTerm }),
  });
  if (!res.ok) throw new Error("Failed to add glossary term");
  return res.json();
}
```

- [ ] **Step 2: Build the Settings page**

Default voice is a per-browser convenience stored in `localStorage` (no
dedicated backend table for it — the spec's schema only tracks per-project
voice assignments, so a personal "preferred default" is client-side only).

```typescript
// frontend/app/settings/page.tsx
"use client";

import { useEffect, useState } from "react";
import { createGlossaryTerm, getGlossaryTerms, getVoiceCatalog } from "@/lib/api";
import type { GlossaryTerm, VoiceCatalogEntry } from "@/lib/types";

const DEFAULT_VOICE_STORAGE_KEY = "default_voice_id";

export default function SettingsPage() {
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [sourceTerm, setSourceTerm] = useState("");
  const [targetTerm, setTargetTerm] = useState("");
  const [catalog, setCatalog] = useState<VoiceCatalogEntry[]>([]);
  const [defaultVoiceId, setDefaultVoiceId] = useState("");

  useEffect(() => {
    getGlossaryTerms().then(setTerms);
    getVoiceCatalog().then(setCatalog);
    setDefaultVoiceId(localStorage.getItem(DEFAULT_VOICE_STORAGE_KEY) ?? "");
  }, []);

  async function handleAddTerm(e: React.FormEvent) {
    e.preventDefault();
    if (!sourceTerm || !targetTerm) return;
    const created = await createGlossaryTerm(sourceTerm, targetTerm);
    setTerms((prev) => [...prev, created]);
    setSourceTerm("");
    setTargetTerm("");
  }

  function handleDefaultVoiceChange(voiceId: string) {
    setDefaultVoiceId(voiceId);
    localStorage.setItem(DEFAULT_VOICE_STORAGE_KEY, voiceId);
  }

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Cài đặt</h1>

      <section className="mb-8">
        <h2 className="mb-3 font-medium">Giọng đọc mặc định</h2>
        <select
          className="w-full rounded border p-2"
          value={defaultVoiceId}
          onChange={(e) => handleDefaultVoiceChange(e.target.value)}
        >
          <option value="">Không đặt mặc định</option>
          {catalog.map((v) => (
            <option key={`${v.engine}-${v.voice_id}`} value={v.voice_id}>
              {v.name} ({v.engine === "edge_tts" ? "edge-tts" : "Gemini TTS"})
            </option>
          ))}
        </select>
      </section>

      <section>
        <h2 className="mb-3 font-medium">Bảng thuật ngữ chung</h2>
        <form onSubmit={handleAddTerm} className="mb-4 flex gap-2">
          <input
            className="flex-1 rounded border p-2"
            placeholder="Từ gốc (VD: Claude)"
            value={sourceTerm}
            onChange={(e) => setSourceTerm(e.target.value)}
          />
          <input
            className="flex-1 rounded border p-2"
            placeholder="Giữ nguyên thành (VD: Claude)"
            value={targetTerm}
            onChange={(e) => setTargetTerm(e.target.value)}
          />
          <button type="submit" className="rounded bg-blue-600 px-4 py-2 text-white">
            Thêm
          </button>
        </form>

        <ul className="space-y-1">
          {terms.map((term) => (
            <li key={term.id} className="rounded border p-2 text-sm">
              {term.source_term} → {term.target_term}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Wire the default voice into the Phase 6 voice-selection page**

```typescript
// frontend/app/projects/[id]/voices/page.tsx  (modify the speaker-mapping initialization inside `load()`)
      const defaultVoiceId = localStorage.getItem("default_voice_id");
      const defaultVoice = defaultVoiceId
        ? voiceCatalog.find((v) => v.voice_id === defaultVoiceId)
        : undefined;

      setCatalog(voiceCatalog);
      setAssignments(
        speakers.map((speaker, i) => ({
          speaker_label: speaker,
          engine: defaultVoice?.engine ?? "edge_tts",
          voice_id:
            defaultVoice?.voice_id ??
            edgeVoices[i % edgeVoices.length]?.voice_id ??
            edgeVoices[0]?.voice_id ??
            "",
          speed: 1.0,
          pitch: 0.0,
        }))
      );
```

- [ ] **Step 4: Run the frontend suite**

Run: `cd frontend && npm test`
Expected: PASS (no new tests added here since this task is thin wrappers over already-tested endpoints and a localStorage convenience — verify manually per the Definition of Done).

- [ ] **Step 5: Commit**

```bash
git add frontend/app/settings/ frontend/lib/api.ts frontend/lib/types.ts frontend/app/projects/
git commit -m "feat(frontend): add Settings page (glossary + default voice) and wire default voice into voice selection"
```

---

### Task 9: Frontend — Admin page

**Files:**
- Create: `frontend/app/admin/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/types.ts`

**Interfaces:**
- Produces: `lib/api.ts` exports `getAdminUsers()`, `setUserQuota(userId, minutes)`, `getAdminUsage()`.

- [ ] **Step 1: Add API functions**

```typescript
// frontend/lib/types.ts  (append)
export interface AdminUser {
  id: string;
  email: string;
  role: string;
  quota_minutes_limit_per_month: number | null;
}

export interface UsageOverviewRow {
  user_id: string;
  email: string;
  total_cost_usd: number;
  total_units: number;
}
```

```typescript
// frontend/lib/api.ts  (append)
import type { AdminUser, UsageOverviewRow } from "./types";

export async function getAdminUsers(): Promise<AdminUser[]> {
  const res = await apiFetch("/api/admin/users");
  if (!res.ok) throw new Error("Failed to load users");
  return res.json();
}

export async function setUserQuota(userId: string, minutes: number) {
  const res = await apiFetch(`/api/admin/users/${userId}/quota`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ minutes_limit_per_month: minutes }),
  });
  if (!res.ok) throw new Error("Failed to update quota");
  return res.json();
}

export async function getAdminUsage(): Promise<UsageOverviewRow[]> {
  const res = await apiFetch("/api/admin/usage");
  if (!res.ok) throw new Error("Failed to load usage overview");
  return res.json();
}
```

- [ ] **Step 2: Build the Admin page**

```typescript
// frontend/app/admin/page.tsx
"use client";

import { useEffect, useState } from "react";
import { getAdminUsage, getAdminUsers, setUserQuota } from "@/lib/api";
import type { AdminUser, UsageOverviewRow } from "@/lib/types";

export default function AdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [usage, setUsage] = useState<UsageOverviewRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getAdminUsers(), getAdminUsage()])
      .then(([u, us]) => {
        setUsers(u);
        setUsage(us);
      })
      .catch(() => setError("Bạn không có quyền truy cập trang này."));
  }, []);

  async function handleQuotaChange(userId: string, minutes: number) {
    await setUserQuota(userId, minutes);
    setUsers((prev) =>
      prev.map((u) => (u.id === userId ? { ...u, quota_minutes_limit_per_month: minutes } : u))
    );
  }

  if (error) return <p className="p-8 text-red-600">{error}</p>;

  const usageByUser = new Map(usage.map((u) => [u.user_id, u]));

  return (
    <main className="mx-auto max-w-4xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Quản trị</h1>

      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 pr-4">Email</th>
            <th className="py-2 pr-4">Vai trò</th>
            <th className="py-2 pr-4">Hạn mức (phút/tháng)</th>
            <th className="py-2">Chi phí đã dùng</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id} className="border-b">
              <td className="py-2 pr-4">{user.email}</td>
              <td className="py-2 pr-4">{user.role}</td>
              <td className="py-2 pr-4">
                <input
                  type="number"
                  className="w-24 rounded border p-1"
                  defaultValue={user.quota_minutes_limit_per_month ?? ""}
                  onBlur={(e) => {
                    const value = Number(e.target.value);
                    if (!Number.isNaN(value)) handleQuotaChange(user.id, value);
                  }}
                />
              </td>
              <td className="py-2">
                ${(usageByUser.get(user.id)?.total_cost_usd ?? 0).toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/admin/ frontend/lib/api.ts frontend/lib/types.ts
git commit -m "feat(frontend): add Admin page (user list, quota editor, usage overview)"
```

---

## Definition of Done for Phase 9

- [ ] `cd backend && pytest` passes (all Phase 1-9 tests, including every earlier phase's tests updated in Task 2 Step 5).
- [ ] `cd frontend && npm test` passes.
- [ ] Manually: register a new user via `/register`, confirm a Supabase Auth user and a `profiles` row both exist, log in via `/login`, and confirm `/dashboard` loads only that user's projects.
- [ ] Manually: promote a user to `role = 'admin'` directly in Supabase's table editor, confirm `/admin` becomes accessible and `/admin` is a 403 for non-admins.
- [ ] Manually: as admin, set a user's quota, confirm it persists; run a project through transcribe/translate/dub and confirm `usage_logs` rows and the `/admin` usage column reflect real cost estimates.
- [ ] Manually: add a glossary term and a default voice via `/settings`, confirm the glossary term is respected in a subsequent translation and the default voice pre-fills on the next project's voice-selection step.
- [ ] Report back to the user that all 9 phases are complete, with a summary of what was built and any deviations from the plans across all phases.
