# AI Video Translator & Dubbing — Design Spec

Status: Approved by user (2026-09-07). Ready for implementation planning.

## 1. Purpose & Scope

A web application that takes a user-uploaded video (or a YouTube/TikTok URL),
transcribes the spoken audio, translates it, generates dubbed speech in the
target language, synchronizes the new audio with the original video timing,
and produces a final video the user can preview and export — optionally with
Vietnamese subtitles.

Primary use case: the user translates and re-dubs their own YouTube/TikTok
videos (source: EN/ZH/JA) into Vietnamese, to re-publish. The product is
built for personal/internal use first, but the architecture (full auth,
per-user quotas, admin role) is designed so it can grow into a public SaaS
later without a rewrite.

## 2. Requirements Summary

### Users & Access
- Full registration/login via Supabase Auth.
- Roles: `user` and `admin`.
- Admins can view all users and set a per-user monthly minutes quota.

### Languages
- Source languages actively targeted: English, Chinese, Japanese.
- Target language actively targeted: Vietnamese.
- The pipeline is architected language-agnostic (any → any); source/target
  are per-project fields, not hardcoded.
- UI language: Vietnamese only. No i18n framework needed at this stage.

### Video Input
- Max duration: 60 minutes. Max file size: 2 GB.
- Accepted formats: anything FFmpeg can read (MP4, MOV, MKV, AVI, WebM, FLV, …).
- Input methods: direct file upload, or URL import from YouTube/TikTok via
  `yt-dlp` (for videos the user owns/has rights to).
- One video processed at a time per project; multiple projects can be queued
  sequentially (no parallel processing requirement).
- Output resolution: user-selectable per export. Default behavior is to copy
  the original video stream (no re-encode, no quality loss, fast) when the
  user keeps the original resolution; re-encoding only happens when the user
  explicitly picks a different resolution.
- Output aspect ratio always matches the source (no auto-crop to 9:16).

### Speech-to-Text
- Primary engine: **ElevenLabs Scribe** (word-level timestamps + speaker
  diarization in a single call).
- Fallback engine: **Whisper running locally** (`faster-whisper`, default
  model size `medium`), used automatically when Scribe fails or the
  account's ElevenLabs quota is exhausted.
- Diarization is required — some source videos have multiple speakers, and
  each speaker gets mapped to a distinct dubbing voice later.

### Translation
- Engine is chosen per project: **Gemini** or **OpenAI**, both keys already
  held by the user (`.env`).
- Translation strategy: the whole transcript is used as context; segments
  are translated in chunks (~10–20 sentences) rather than sentence-by-sentence,
  to preserve pronouns/references correctly.
- A **global glossary** (source term → target term, not translated) applies
  across all projects.
- Tone: natural, conversational Vietnamese (as spoken on YouTube/TikTok),
  not formal/literal.
- Translation is **not** constrained to match spoken-duration of the source
  sentence — full meaning is preserved even if that makes the sentence
  longer or shorter than the original. Timing drift is absorbed downstream
  (see §Timing Sync).

### Timing Synchronization
Order of correction applied per segment, cheapest/least-destructive first:
1. TTS **speaking rate** is adjusted per segment to get as close as possible
   to the original segment's duration.
2. Natural silence gaps between segments are used as slack/padding.
3. As a last resort, FFmpeg `atempo` stretches/compresses the generated
   audio to force-fit the original segment's time window.

### Text-to-Speech
- Primary engine: **edge-tts** (free, natural-sounding Vietnamese voices:
  HoaiMy/NamMinh). This is an unofficial API and can break without notice.
- On edge-tts failure, the user is **notified and asked** whether to
  fall back to **Gemini TTS** — this is not an automatic silent switch.
- Voice selection: user picks from a voice catalog, with audio preview.
  Detected speakers are auto-mapped to distinct voices; user can override
  and adjust per-voice speed/pitch.
- No voice cloning (explicitly out of scope — Vietnamese cloning quality is
  poor and the user's machine has no GPU).

### Audio Mixing
Chosen **per project**, one of:
- **A. Silent background** — only the new Vietnamese voice track, original
  audio fully removed.
- **B. Music preserved** — original vocals removed via **Demucs** source
  separation, new voice mixed over the remaining background music/effects
  stem, with a user-adjustable volume slider. (Note: Demucs on CPU runs at
  roughly 1.5× real-time — a 60-minute video's separation step alone takes
  ~90 minutes.)
- **C. Ducking** — original full audio kept but automatically lowered in
  volume under the new voice track, with a user-adjustable slider.

### Subtitles
- Vietnamese only (no source-language or bilingual subtitle requirement).
- Format: SRT.
- Three deliverables generated together:
  1. A standalone `.srt` file (downloadable).
  2. A video with the subtitle **soft-embedded** (toggleable in players that
     support it, e.g. MKV/MP4 subtitle track).
  3. A second video with the subtitle **burned in** (hardcoded, not
     toggleable), with user-configurable font size/color/position
     (TikTok-style: large text, black outline, centered).

### Editing
- Editor style: sentence-list table (timestamp | source text | translated
  text | play | regenerate) for the first version. A waveform/timeline
  editor is an explicitly deferred future phase.
- Users can edit: the source transcript text, and the translated text.
- Users can preview (play) each dubbed sentence individually, and can
  regenerate just one sentence's dubbed audio (not the whole video) after
  editing it.

### Processing / Background Jobs
- All heavy operations (transcribe, translate, dub, export) run as
  **background jobs** (Celery + Redis), never synchronously inside an HTTP
  request, to avoid timeouts on 60-minute videos.
- The UI shows per-step progress percentage plus a realtime log, delivered
  over **WebSocket**.
- Closing the browser tab does **not** stop processing — the job continues
  server-side and the user sees the result when they return.

### Storage & Data Lifecycle
- Files (source video, intermediate audio, final exports) are stored in
  **Cloudflare R2**.
- Temporary intermediate files (extracted audio, separated stems, per-segment
  TTS clips) are deleted as soon as they are no longer needed by a
  downstream step.
- The full project (video + exports) is deleted 7 days after creation; the
  user is warned in-app 1 day before deletion.

### Database
- **PostgreSQL hosted on Supabase**, used for both local development and
  production (no separate local Postgres instance) — this is a conscious
  trade-off accepted by the user: local development requires network
  connectivity to Supabase.
- **Supabase Auth** provides authentication; the backend verifies the
  Supabase-issued JWT on each request.

### Screens
Landing page · Login/Register · Dashboard (project list + usage) · New
Project (upload/URL + language + audio-mode selection) · Editor (transcript
+ translation + voice assignment, tabs on one screen) · Preview/Export ·
Settings (global glossary, default voice preferences) · Admin (user list,
per-user quota, usage/cost overview) · Project History.

### Quotas & Cost Tracking
- Every external API call (STT/translation/TTS) is logged with provider,
  operation, cost, and unit count, tied to the user and project — for
  visibility, not automatic enforcement beyond quota limits.
- Admins set a monthly minutes quota per user manually (no fixed formula).

### API Keys / Secrets
- All third-party API keys (ElevenLabs, Gemini, OpenAI, Supabase, Cloudflare
  R2) are supplied via `.env` for now. The user registers for these
  services themselves; this project only provides setup documentation. No
  in-app "enter your API key" settings screen is built at this stage.

## 3. Architecture

```
┌─────────────┐      REST + WebSocket      ┌──────────────────┐
│  Next.js     │ ─────────────────────────▶│  FastAPI backend  │
│  (Tailwind + │                            │  (verifies        │
│  shadcn/ui)  │◀─── WS progress/log ───────│   Supabase JWT)   │
└─────────────┘                            └─────────┬─────────┘
       │                                              │ enqueue
       │ Supabase Auth SDK                             ▼
       │                                    ┌──────────────────┐
       ▼                                    │  Redis (queue)    │
┌─────────────┐                            └─────────┬─────────┘
│  Supabase    │                                      ▼
│  (Postgres + │                            ┌──────────────────┐
│   Auth)      │◀──── SQLModel ─────────────│  Celery workers   │
└─────────────┘                            │  - STT (ElevenLabs/│
                                            │    Whisper local) │
┌─────────────┐                            │  - Translate       │
│  Cloudflare  │◀──── upload/download ──────│    (Gemini/OpenAI) │
│  R2 (video,  │                            │  - TTS (edge-tts/  │
│   audio)     │                            │    Gemini TTS)     │
└─────────────┘                            │  - FFmpeg/Demucs   │
                                            │    (sync + mux)    │
                                            └──────────────────┘
```

Docker Compose (same file for dev and prod, different env vars) runs:
backend API, Celery worker, Redis, frontend. Postgres is intentionally
**not** in the compose file — Supabase (remote) is used in both dev and
prod per the requirements above.

## 4. Tech Stack

| Component | Choice | Why |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + TailwindCSS + shadcn/ui | SSR helps the public landing page's SEO; shadcn/ui gives a modern, highly customizable component set suited to a data-heavy editor. No dark mode. |
| Backend | FastAPI (Python 3.12, in Docker) | Demucs, edge-tts, and the FFmpeg/audio pipeline are native Python; avoids bridging to a second runtime. Python 3.12 (not the host's 3.14) is used inside Docker for PyTorch/Demucs/faster-whisper compatibility. |
| ORM | SQLModel + Alembic | Prisma for Python (`prisma-client-py`) is archived/unmaintained (confirmed via GitHub — archived 2025-04-15, capped at Python 3.10). SQLModel is FastAPI-native, type-safe, Pydantic-based; Alembic handles migrations. |
| Queue | Celery + Redis | Required because processing a 60-minute video takes on the order of hours; jobs must survive the user closing their browser tab. |
| Realtime | WebSocket | Two-way channel used to stream progress % and log lines per job. |
| Database / Auth | Supabase (Postgres + Auth) | Single hosted service for both, used consistently across dev and prod. |
| Storage | Cloudflare R2 | No egress fees, cost-effective for video-sized objects. |
| Video/audio tooling | FFmpeg, Demucs, yt-dlp | FFmpeg for mux/encode/atempo; Demucs for vocal/music separation; yt-dlp for YouTube/TikTok import. |
| Deployment | Railway (frontend + backend + worker + Redis), Supabase, Cloudflare R2 | Railway runs long-lived worker processes (unlike serverless platforms, which can't host multi-hour jobs). |
| Repo layout | Monorepo: `frontend/`, `backend/` | Single clone, single source of truth for the two halves of the app. |

## 5. Database Schema

```
profiles (mirrors supabase auth.users)
  id (= auth.users.id), email, role[user|admin], created_at

quotas
  id, user_id → profiles, minutes_limit_per_month, set_by_admin_id, updated_at

projects
  id, user_id → profiles, title, source_language, target_language,
  status[draft|transcribing|translating|dubbing|ready|failed],
  audio_mode[silent|music_separated|ducking],
  translate_engine[gemini|openai],
  created_at, updated_at, warn_at, expires_at

videos
  id, project_id → projects, source_type[upload|youtube|tiktok],
  source_url, storage_path, duration_sec, resolution, codec,
  file_size_bytes, uploaded_at

transcript_segments
  id, project_id → projects, seq_index, start_time, end_time,
  speaker_label, source_text, source_text_edited, confidence

translation_segments
  id, segment_id → transcript_segments (1-1),
  translated_text, translated_text_edited

voices
  id, project_id → projects, speaker_label, engine[edge-tts|gemini-tts],
  voice_id, speed, pitch

dubbed_segments
  id, segment_id → transcript_segments (1-1),
  audio_storage_path, duration_sec, status, generated_at

jobs
  id, project_id → projects, job_type[transcribe|translate|dub|export],
  status[queued|running|done|failed], progress_pct, current_step,
  error_message, started_at, finished_at

exports
  id, project_id → projects, export_type[video|video_hardsub|srt],
  storage_path, resolution, created_at, expires_at

glossary_terms
  id, user_id → profiles, source_term, target_term

usage_logs
  id, user_id → profiles, project_id → projects,
  api_provider, operation, cost_usd, units, created_at
```

Key relationships: a project has many transcript segments; each transcript
segment has exactly one translation segment and (once dubbed) exactly one
dubbed-audio segment; a project has many voices (one per detected speaker),
many jobs (one per pipeline stage run), and many exports (one per export
type requested).

## 6. API Design

Auth is handled client-side via the Supabase SDK; the backend only verifies
the Supabase-issued JWT via middleware.

```
POST   /api/projects
GET    /api/projects
GET    /api/projects/{id}
PATCH  /api/projects/{id}
DELETE /api/projects/{id}

POST   /api/projects/{id}/upload            (multipart file)
POST   /api/projects/{id}/import-url        {url}

POST   /api/projects/{id}/transcribe        → enqueue Celery job
GET    /api/projects/{id}/transcript
PATCH  /api/projects/{id}/transcript/{segment_id}

POST   /api/projects/{id}/translate         {engine}  → enqueue job
GET    /api/projects/{id}/translation
PATCH  /api/projects/{id}/translation/{segment_id}

GET    /api/voices/catalog
GET    /api/voices/preview?engine=&voice_id=
PUT    /api/projects/{id}/voices            (assign voice per speaker)

POST   /api/projects/{id}/dub               → enqueue TTS+sync+mux job
POST   /api/projects/{id}/segments/{id}/regenerate

GET    /api/projects/{id}/preview
POST   /api/projects/{id}/export            {type: video|video_hardsub|srt}
GET    /api/projects/{id}/exports
GET    /api/projects/{id}/exports/{id}/download

GET    /api/projects/{id}/status
WS     /ws/projects/{id}/progress

GET/POST /api/glossary
GET    /api/admin/users
PATCH  /api/admin/users/{id}/quota
GET    /api/admin/usage
```

Every endpoint that triggers transcription, translation, dubbing, or export
enqueues a background job and returns immediately; it does not block the
HTTP request while the job runs.

## 7. Folder Structure

```
tool/
├── frontend/                          # Next.js
│   ├── app/
│   │   ├── (auth)/login/ register/
│   │   ├── dashboard/
│   │   ├── projects/[id]/
│   │   │   ├── transcript/ translate/ voices/ preview/ export/
│   │   ├── settings/
│   │   ├── admin/
│   │   └── history/
│   ├── components/
│   ├── lib/                           # supabase client, api client, ws client
│   └── ...
│
├── backend/                           # FastAPI
│   ├── app/
│   │   ├── api/                       # routers per resource
│   │   ├── models/                    # SQLModel
│   │   ├── services/
│   │   │   ├── stt/                   # elevenlabs.py, whisper_local.py
│   │   │   ├── translation/           # gemini.py, openai.py
│   │   │   ├── tts/                   # edge_tts.py, gemini_tts.py
│   │   │   ├── audio/                 # demucs.py, ducking.py, sync.py, ffmpeg_utils.py
│   │   │   ├── storage/               # r2.py
│   │   │   └── downloader/            # yt_dlp.py
│   │   ├── workers/                   # celery tasks
│   │   ├── core/                      # config, jwt auth, celery app, ws manager
│   │   ├── db/                        # session, models base
│   │   └── main.py
│   ├── alembic/
│   ├── Dockerfile
│   └── pyproject.toml
│
├── docker-compose.yml                 # backend + worker + redis + frontend
├── .env.example
├── .gitignore
└── README.md
```

## 8. Implementation Assumptions (not gated on further user confirmation)

- Whisper local fallback defaults to the `medium` model size, overridable
  via `.env`.
- Dev requires internet connectivity to reach Supabase (direct consequence
  of using Supabase in dev, not local Postgres).
- Backend runs Python 3.12 inside Docker regardless of the host machine's
  Python version.
- FFmpeg ships inside the backend Docker image; the host machine does not
  need it installed separately.

## 9. Explicitly Out of Scope (for this phase)

- Voice cloning.
- Timeline/waveform editor (deferred to a future phase; sentence-list
  editor ships first).
- Source-language or bilingual subtitles (Vietnamese-only for now).
- In-app API key management UI (keys are `.env`-only for now).
- Automatic quota enforcement beyond manual admin-set limits.
- Any "offline/private" processing mode — every project uses the cloud
  engines described above.

## 10. Implementation Phases (for the follow-up plan)

1. Project setup — repo scaffolding, Docker Compose, frontend/backend
   health check, Supabase connection, CI-less local dev loop.
2. Upload — file upload + YouTube/TikTok URL import, video metadata
   extraction, project creation flow.
3. Speech-to-text — ElevenLabs Scribe integration, Whisper local fallback,
   Celery job wiring, WebSocket progress.
4. Transcript editor — sentence-list UI, edit/save segment text.
5. Translation — Gemini/OpenAI integration, chunked context-aware
   translation, glossary application, translation editor UI.
6. Text-to-speech — edge-tts integration, Gemini TTS fallback prompt,
   voice catalog + preview, speaker→voice mapping UI.
7. FFmpeg pipeline — timing sync (rate adjust → silence padding →
   atempo), Demucs separation / ducking, mux into final video, subtitle
   burn-in and soft-embed.
8. Preview & export — preview player, per-segment regenerate, export
   flow (video / video+hardsub / srt), download, R2 lifecycle (temp
   cleanup, 7-day expiry with 1-day warning).
9. Auth, admin, quotas — Supabase Auth wiring, role-based access,
   admin screens (user list, quota editor, usage/cost overview),
   settings screen (global glossary, default voice prefs).

Each phase ends with tests run, errors checked, and a report back before
moving to the next phase — no phase proceeds past a decision point that
needs user confirmation without stopping to ask first.
