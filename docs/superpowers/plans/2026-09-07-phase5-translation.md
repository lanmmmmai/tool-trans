# Phase 5: Translation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate the (possibly user-edited) transcript into the project's target language using either Gemini or OpenAI, chunked with full-transcript context and glossary application, as a background job with progress, with a translation editor for the user to refine the result.

**Architecture:** A `TranslationSegment` model (1-1 with `TranscriptSegment`) and a `GlossaryTerm` model; a `translation` service package with a `Translator` interface and Gemini/OpenAI implementations that both take the *full transcript* plus a chunk of segments and return chunk-aligned translations; a `translate_task` Celery job following the same template as `transcribe_task`; `POST /translate`, `GET /translation`, `PATCH /translation/{segment_id}` endpoints; a glossary CRUD endpoint; a translation editor page.

**Tech Stack:** FastAPI, Celery, Gemini API (`google-genai`), OpenAI API (`openai` SDK), WebSocket (reusing Phase 3's `WSManager`).

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- Engine chosen per project: Gemini or OpenAI (spec §Dịch thuật; `Project.translate_engine`).
- Translation uses the full transcript as context, translated in ~10-20-sentence chunks, not sentence-by-sentence (spec §Dịch thuật, discovery Q25-C).
- A global glossary (source term → target term, not translated) applies to every project (spec §Dịch thuật, discovery Q26-D).
- Tone: natural conversational Vietnamese, not formal/literal (spec §Dịch thuật).
- Translation is **not** length-constrained — full meaning is preserved even if the sentence gets longer or shorter; timing drift is corrected downstream in Phase 7 (spec §Dịch thuật, §Đồng bộ thời gian, discovery Q31-B).
- The "effective source text" for translation input is `source_text_edited if source_text_edited is not None else source_text` (Phase 4's rule).
- Auth is still the Phase-2/3/4 stub (`get_current_user_id`); `GlossaryTerm.user_id` is populated from that stub for now and becomes meaningful once Phase 9 lands real accounts.

## Established Interfaces (produced here, consumed by later phases)

- `app.models.translation_segment.TranslationSegment` — SQLModel table (fields per spec §5), unique on `segment_id`.
- `app.models.glossary_term.GlossaryTerm` — SQLModel table (fields per spec §5).
- `app.services.translation.base.Translator` — `translate_chunk(full_transcript: str, chunk: list[ChunkSegment], glossary: list[GlossaryEntry], target_language: str) -> list[str]` (returns translated text, one per input segment, same order). `ChunkSegment(seq_index: int, text: str)`, `GlossaryEntry(source_term: str, target_term: str)`.
- `app.services.translation.gemini.GeminiTranslator(Translator)`, `app.services.translation.openai.OpenAITranslator(Translator)`.
- `app.services.translation.chunker.chunk_segments(segments: list[TranscriptSegment], chunk_size: int = 15) -> list[list[TranscriptSegment]]` — used by `translate_task` and reusable by nothing else, but documented here since it is a general-purpose helper.
- The "effective translated text" resolution rule (used starting Phase 6): `translated_text_edited if translated_text_edited is not None else translated_text`.
- `app.workers.translate.translate_task(project_id: str, engine: str)` — Celery task, same status/progress/broadcast template as `transcribe_task`.

---

### Task 1: `TranslationSegment` and `GlossaryTerm` models + migration

**Files:**
- Create: `backend/app/models/translation_segment.py`
- Create: `backend/app/models/glossary_term.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_translation_models.py`

**Interfaces:**
- Produces: `TranslationSegment`, `GlossaryTerm` SQLModel classes.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_translation_models.py
from sqlmodel import Session, SQLModel, create_engine

from app.models.glossary_term import GlossaryTerm
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_create_translation_segment_linked_to_transcript_segment():
    engine = make_engine()
    with Session(engine) as session:
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        transcript_seg = TranscriptSegment(
            project_id=project.id, seq_index=0, start_time=0, end_time=1,
            speaker_label="speaker_1", source_text="Hello",
        )
        session.add(transcript_seg)
        session.commit()
        session.refresh(transcript_seg)

        translation_seg = TranslationSegment(
            segment_id=transcript_seg.id, translated_text="Xin chào"
        )
        session.add(translation_seg)
        session.commit()
        session.refresh(translation_seg)

        assert translation_seg.translated_text_edited is None
        assert translation_seg.segment_id == transcript_seg.id


def test_create_glossary_term():
    engine = make_engine()
    with Session(engine) as session:
        term = GlossaryTerm(user_id="u1", source_term="Claude", target_term="Claude")
        session.add(term)
        session.commit()
        session.refresh(term)
        assert term.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_translation_models.py -v`
Expected: FAIL — models don't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/translation_segment.py
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class TranslationSegment(SQLModel, table=True):
    __tablename__ = "translation_segments"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    segment_id: str = Field(foreign_key="transcript_segments.id", unique=True, index=True)
    translated_text: str
    translated_text_edited: Optional[str] = None
```

```python
# backend/app/models/glossary_term.py
from uuid import uuid4

from sqlmodel import Field, SQLModel


class GlossaryTerm(SQLModel, table=True):
    __tablename__ = "glossary_terms"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    source_term: str
    target_term: str
```

```python
# backend/app/models/__init__.py
from app.models.glossary_term import GlossaryTerm  # noqa: F401
from app.models.job import Job  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.transcript_segment import TranscriptSegment  # noqa: F401
from app.models.translation_segment import TranslationSegment  # noqa: F401
from app.models.video import Video  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_translation_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Generate migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add translation_segments and glossary_terms tables" --autogenerate && alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/translation_segment.py backend/app/models/glossary_term.py backend/app/models/__init__.py backend/tests/test_translation_models.py backend/alembic/versions/
git commit -m "feat(backend): add TranslationSegment and GlossaryTerm models + migration"
```

---

### Task 2: Chunking helper

**Files:**
- Create: `backend/app/services/translation/__init__.py`
- Create: `backend/app/services/translation/chunker.py`
- Create: `backend/tests/test_chunker.py`

**Interfaces:**
- Produces: `app.services.translation.chunker.chunk_segments(segments, chunk_size=15) -> list[list[TranscriptSegment]]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chunker.py
from app.models.transcript_segment import TranscriptSegment
from app.services.translation.chunker import chunk_segments


def make_segment(i: int) -> TranscriptSegment:
    return TranscriptSegment(
        project_id="p1", seq_index=i, start_time=i, end_time=i + 1,
        speaker_label="speaker_1", source_text=f"sentence {i}",
    )


def test_chunk_segments_splits_into_groups_of_chunk_size():
    segments = [make_segment(i) for i in range(32)]
    chunks = chunk_segments(segments, chunk_size=15)

    assert len(chunks) == 3
    assert len(chunks[0]) == 15
    assert len(chunks[1]) == 15
    assert len(chunks[2]) == 2
    assert chunks[0][0].seq_index == 0
    assert chunks[2][-1].seq_index == 31


def test_chunk_segments_handles_empty_list():
    assert chunk_segments([], chunk_size=15) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_chunker.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/translation/__init__.py
```

```python
# backend/app/services/translation/chunker.py
from app.models.transcript_segment import TranscriptSegment


def chunk_segments(
    segments: list[TranscriptSegment], chunk_size: int = 15
) -> list[list[TranscriptSegment]]:
    return [segments[i : i + chunk_size] for i in range(0, len(segments), chunk_size)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_chunker.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/translation/__init__.py backend/app/services/translation/chunker.py backend/tests/test_chunker.py
git commit -m "feat(backend): add transcript chunking helper for translation"
```

---

### Task 3: `Translator` interface + Gemini and OpenAI implementations

**Files:**
- Create: `backend/app/services/translation/base.py`
- Create: `backend/app/services/translation/gemini.py`
- Create: `backend/app/services/translation/openai.py`
- Create: `backend/tests/test_translation_engines.py`

**Interfaces:**
- Produces: `Translator` (ABC), `ChunkSegment`, `GlossaryEntry` dataclasses, `TranslationProviderError(Exception)`; `GeminiTranslator`, `OpenAITranslator`.

Both engines are prompted the same way: full transcript as context, the
current chunk's sentences numbered, the glossary as a do-not-translate list,
and an instruction to return one JSON array of translated strings in the
same order and count as the input — this is what makes chunk-aligned
parsing reliable regardless of provider.

- [ ] **Step 1: Add SDK dependencies**

Add to `backend/pyproject.toml`'s `dependencies`: `"google-genai>=0.3"`, `"openai>=1.50"`.
Run: `cd backend && pip install -e ".[dev]"`

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_translation_engines.py
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.translation.base import ChunkSegment, GlossaryEntry, TranslationProviderError
from app.services.translation.gemini import GeminiTranslator
from app.services.translation.openai import OpenAITranslator


CHUNK = [ChunkSegment(seq_index=0, text="Hello"), ChunkSegment(seq_index=1, text="World")]
GLOSSARY = [GlossaryEntry(source_term="Claude", target_term="Claude")]


def test_gemini_translator_parses_json_array_response():
    translator = GeminiTranslator(api_key="fake")

    with patch("app.services.translation.gemini.genai.Client") as MockClient:
        mock_client = MockClient.return_value
        mock_response = MagicMock()
        mock_response.text = json.dumps(["Xin chào", "Thế giới"])
        mock_client.models.generate_content.return_value = mock_response

        result = translator.translate_chunk(
            full_transcript="Hello World", chunk=CHUNK, glossary=GLOSSARY, target_language="vi"
        )

    assert result == ["Xin chào", "Thế giới"]


def test_gemini_translator_raises_on_mismatched_count():
    translator = GeminiTranslator(api_key="fake")

    with patch("app.services.translation.gemini.genai.Client") as MockClient:
        mock_client = MockClient.return_value
        mock_response = MagicMock()
        mock_response.text = json.dumps(["Only one"])
        mock_client.models.generate_content.return_value = mock_response

        with pytest.raises(TranslationProviderError):
            translator.translate_chunk(
                full_transcript="Hello World", chunk=CHUNK, glossary=GLOSSARY, target_language="vi"
            )


def test_openai_translator_parses_json_array_response():
    translator = OpenAITranslator(api_key="fake")

    with patch("app.services.translation.openai.OpenAI") as MockOpenAI:
        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = json.dumps(["Xin chào", "Thế giới"])
        mock_client.chat.completions.create.return_value.choices = [
            MagicMock(message=mock_message)
        ]

        result = translator.translate_chunk(
            full_transcript="Hello World", chunk=CHUNK, glossary=GLOSSARY, target_language="vi"
        )

    assert result == ["Xin chào", "Thế giới"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_translation_engines.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 4: Write minimal implementation**

```python
# backend/app/services/translation/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChunkSegment:
    seq_index: int
    text: str


@dataclass
class GlossaryEntry:
    source_term: str
    target_term: str


class TranslationProviderError(Exception):
    pass


def build_prompt(
    full_transcript: str,
    chunk: list[ChunkSegment],
    glossary: list[GlossaryEntry],
    target_language: str,
) -> str:
    glossary_lines = "\n".join(f"- {g.source_term} -> {g.target_term}" for g in glossary)
    numbered_chunk = "\n".join(f"{i + 1}. {seg.text}" for i, seg in enumerate(chunk))

    return f"""You are dubbing a YouTube/TikTok video into {target_language}.
Translate naturally and conversationally, as a native speaker would say it
out loud — not a stiff literal translation. Do NOT shorten or summarize;
preserve the full meaning of each sentence even if the translation ends up
longer or shorter than the original.

Full transcript for context (do not translate this block, it is only for
understanding pronouns/references):
---
{full_transcript}
---

Glossary — do NOT translate these terms, keep them exactly as-is:
{glossary_lines or "(none)"}

Translate ONLY the following {len(chunk)} numbered sentences into
{target_language}. Return a JSON array of exactly {len(chunk)} strings, in
the same order, with no numbering and no extra commentary — just the JSON
array.

{numbered_chunk}
"""


class Translator(ABC):
    @abstractmethod
    def translate_chunk(
        self,
        full_transcript: str,
        chunk: list[ChunkSegment],
        glossary: list[GlossaryEntry],
        target_language: str,
    ) -> list[str]:
        raise NotImplementedError
```

```python
# backend/app/services/translation/gemini.py
import json

from google import genai

from app.services.translation.base import (
    ChunkSegment,
    GlossaryEntry,
    Translator,
    TranslationProviderError,
    build_prompt,
)


class GeminiTranslator(Translator):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model

    def translate_chunk(
        self,
        full_transcript: str,
        chunk: list[ChunkSegment],
        glossary: list[GlossaryEntry],
        target_language: str,
    ) -> list[str]:
        prompt = build_prompt(full_transcript, chunk, glossary, target_language)
        client = genai.Client(api_key=self.api_key)

        response = client.models.generate_content(model=self.model, contents=prompt)

        try:
            result = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise TranslationProviderError(f"Gemini returned non-JSON output: {exc}") from exc

        if not isinstance(result, list) or len(result) != len(chunk):
            raise TranslationProviderError(
                f"Gemini returned {len(result) if isinstance(result, list) else 'invalid'} "
                f"items, expected {len(chunk)}"
            )
        return result
```

```python
# backend/app/services/translation/openai.py
import json

from openai import OpenAI

from app.services.translation.base import (
    ChunkSegment,
    GlossaryEntry,
    Translator,
    TranslationProviderError,
    build_prompt,
)


class OpenAITranslator(Translator):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model

    def translate_chunk(
        self,
        full_transcript: str,
        chunk: list[ChunkSegment],
        glossary: list[GlossaryEntry],
        target_language: str,
    ) -> list[str]:
        prompt = build_prompt(full_transcript, chunk, glossary, target_language)
        client = OpenAI(api_key=self.api_key)

        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"} if False else None,
        )
        content = response.choices[0].message.content

        try:
            result = json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise TranslationProviderError(f"OpenAI returned non-JSON output: {exc}") from exc

        if not isinstance(result, list) or len(result) != len(chunk):
            raise TranslationProviderError(
                f"OpenAI returned {len(result) if isinstance(result, list) else 'invalid'} "
                f"items, expected {len(chunk)}"
            )
        return result
```

Note: the `response_format={"type": "json_object"} if False else None` line
is deliberately inert here — plain chat completions with a JSON-array
instruction in the prompt are used instead of the object-only
`json_object` mode (which requires the word "json" plus an object, not
array, shape). Simplify by just removing that kwarg entirely:

```python
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_translation_engines.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/translation/base.py backend/app/services/translation/gemini.py backend/app/services/translation/openai.py backend/tests/test_translation_engines.py backend/pyproject.toml
git commit -m "feat(backend): add Gemini and OpenAI translator implementations"
```

---

### Task 4: `translate_task` Celery task

**Files:**
- Create: `backend/app/workers/translate.py`
- Modify: `backend/app/core/celery_app.py`
- Create: `backend/tests/test_translate_task.py`

**Interfaces:**
- Consumes: `chunk_segments`, `GeminiTranslator`/`OpenAITranslator`, `GlossaryTerm`, `TranscriptSegment`, `TranslationSegment`, `Job`, `ws_manager` (all prior).
- Produces: `app.workers.translate.translate_task(project_id: str, engine: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_translate_task.py
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.glossary_term import GlossaryTerm
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def seed(session):
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi",
        audio_mode="ducking", translate_engine="gemini",
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    for i, text in enumerate(["Hello", "World"]):
        session.add(
            TranscriptSegment(
                project_id=project.id, seq_index=i, start_time=i, end_time=i + 1,
                speaker_label="speaker_1", source_text=text,
            )
        )
    session.add(GlossaryTerm(user_id="u1", source_term="Claude", target_term="Claude"))

    job = Job(project_id=project.id, job_type="translate")
    session.add(job)
    session.commit()
    session.refresh(job)
    return project, job


def test_translate_task_writes_translation_segments_and_marks_job_done():
    engine = make_engine()
    with Session(engine) as session:
        project, job = seed(session)

    with patch("app.workers.translate.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.translate.GeminiTranslator"
    ) as MockGemini, patch("app.workers.translate.broadcast_sync"):
        MockGemini.return_value.translate_chunk.return_value = ["Xin chào", "Thế giới"]

        from app.workers.translate import translate_task

        translate_task.run(project_id=project.id, engine="gemini")

    with Session(engine) as session:
        refreshed_job = session.get(Job, job.id)
        assert refreshed_job.status == "done"

        translations = session.exec(select(TranslationSegment)).all()
        assert len(translations) == 2
        texts = {t.translated_text for t in translations}
        assert texts == {"Xin chào", "Thế giới"}


def test_translate_task_marks_job_failed_on_exception():
    engine = make_engine()
    with Session(engine) as session:
        project, job = seed(session)

    with patch("app.workers.translate.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.translate.GeminiTranslator"
    ) as MockGemini, patch("app.workers.translate.broadcast_sync"):
        MockGemini.return_value.translate_chunk.side_effect = RuntimeError("api down")

        from app.workers.translate import translate_task

        translate_task.run(project_id=project.id, engine="gemini")

    with Session(engine) as session:
        refreshed_job = session.get(Job, job.id)
        assert refreshed_job.status == "failed"
        assert "api down" in refreshed_job.error_message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_translate_task.py -v`
Expected: FAIL — `app.workers.translate` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/workers/translate.py
import asyncio
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.ws_manager import ws_manager
from app.db.session import engine
from app.models.glossary_term import GlossaryTerm
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.services.translation.base import ChunkSegment, GlossaryEntry
from app.services.translation.chunker import chunk_segments
from app.services.translation.gemini import GeminiTranslator
from app.services.translation.openai import OpenAITranslator


def get_session_for_worker() -> Session:
    return Session(engine)


def broadcast_sync(project_id: str, message: dict) -> None:
    asyncio.run(ws_manager.broadcast(project_id, message))


def _effective_source_text(segment: TranscriptSegment) -> str:
    return segment.source_text_edited or segment.source_text


def _build_translator(engine_name: str):
    if engine_name == "openai":
        return OpenAITranslator(api_key=settings.openai_api_key)
    return GeminiTranslator(api_key=settings.gemini_api_key)


@celery_app.task(name="app.workers.translate.translate_task")
def translate_task(project_id: str, engine_name: str = "gemini") -> None:
    session = get_session_for_worker()
    job = session.exec(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == "translate")
        .order_by(Job.started_at.desc().nullslast())
    ).first()
    if job is None:
        session.close()
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.current_step = "translating"
    session.add(job)
    session.commit()
    broadcast_sync(project_id, {"status": "running", "step": "translating", "progress_pct": 5})

    try:
        segments = session.exec(
            select(TranscriptSegment)
            .where(TranscriptSegment.project_id == project_id)
            .order_by(TranscriptSegment.seq_index)
        ).all()
        full_transcript = " ".join(_effective_source_text(s) for s in segments)

        glossary_rows = session.exec(select(GlossaryTerm)).all()
        glossary = [GlossaryEntry(g.source_term, g.target_term) for g in glossary_rows]

        project = session.get(Project, project_id)
        translator = _build_translator(engine_name)

        chunks = chunk_segments(segments, chunk_size=15)
        total_chunks = max(len(chunks), 1)

        for chunk_index, chunk in enumerate(chunks):
            chunk_segments_for_prompt = [
                ChunkSegment(seq_index=s.seq_index, text=_effective_source_text(s)) for s in chunk
            ]
            translations = translator.translate_chunk(
                full_transcript=full_transcript,
                chunk=chunk_segments_for_prompt,
                glossary=glossary,
                target_language=project.target_language,
            )

            for segment, translated_text in zip(chunk, translations):
                session.add(
                    TranslationSegment(segment_id=segment.id, translated_text=translated_text)
                )
            session.commit()

            progress = int(((chunk_index + 1) / total_chunks) * 90) + 5
            job.progress_pct = progress
            session.add(job)
            session.commit()
            broadcast_sync(
                project_id,
                {"status": "running", "step": "translating", "progress_pct": progress},
            )

        job.status = "done"
        job.progress_pct = 100
        job.current_step = "done"
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(project_id, {"status": "done", "progress_pct": 100})
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(project_id, {"status": "failed", "error": str(exc)})
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_translate_task.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Register the task module with Celery**

```python
# backend/app/core/celery_app.py  (update include list)
celery_app = Celery(
    "video_dubbing",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.ping", "app.workers.transcribe", "app.workers.translate"],
)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/translate.py backend/app/core/celery_app.py backend/tests/test_translate_task.py
git commit -m "feat(backend): add translate_task Celery job"
```

---

### Task 5: Translation + glossary endpoints

**Files:**
- Create: `backend/app/api/translation.py`
- Create: `backend/app/api/glossary.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_translation_api.py`
- Create: `backend/tests/test_glossary_api.py`

**Interfaces:**
- Produces: `POST /api/projects/{id}/translate` (body `{"engine": "gemini"|"openai"}`), `GET /api/projects/{id}/translation`, `PATCH /api/projects/{id}/translation/{segment_id}`; `GET/POST /api/glossary`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_translation_api.py
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)


def create_project():
    resp = client.post(
        "/api/projects",
        json={
            "title": "Translate test", "source_language": "en",
            "target_language": "vi", "audio_mode": "ducking",
        },
    )
    return resp.json()["id"]


def test_start_translate_sets_engine_and_enqueues_task():
    project_id = create_project()

    with patch("app.api.translation.translate_task") as mock_task:
        resp = client.post(
            f"/api/projects/{project_id}/translate", json={"engine": "openai"}
        )

    assert resp.status_code == 202, resp.text
    assert resp.json()["job_type"] == "translate"
    mock_task.delay.assert_called_once_with(project_id=project_id, engine_name="openai")

    project_resp = client.get(f"/api/projects/{project_id}")
    assert project_resp.json()["translate_engine"] == "openai"


def test_get_translation_joins_transcript_and_translation():
    project_id = create_project()
    with Session(engine) as session:
        seg = TranscriptSegment(
            project_id=project_id, seq_index=0, start_time=0, end_time=1,
            speaker_label="speaker_1", source_text="Hello",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)
        session.add(TranslationSegment(segment_id=seg.id, translated_text="Xin chào"))
        session.commit()

    resp = client.get(f"/api/projects/{project_id}/translation")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["translated_text"] == "Xin chào"
    assert body[0]["source_text"] == "Hello"


def test_patch_translation_segment():
    project_id = create_project()
    with Session(engine) as session:
        seg = TranscriptSegment(
            project_id=project_id, seq_index=0, start_time=0, end_time=1,
            speaker_label="speaker_1", source_text="Hello",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)
        translation = TranslationSegment(segment_id=seg.id, translated_text="Xin chào")
        session.add(translation)
        session.commit()
        session.refresh(translation)
        translation_id = translation.id

    resp = client.patch(
        f"/api/projects/{project_id}/translation/{translation_id}",
        json={"translated_text_edited": "Chào bạn"},
    )
    assert resp.status_code == 200
    assert resp.json()["translated_text_edited"] == "Chào bạn"
```

```python
# backend/tests/test_glossary_api.py
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)


def test_create_and_list_glossary_terms():
    create_resp = client.post(
        "/api/glossary", json={"source_term": "Claude", "target_term": "Claude"}
    )
    assert create_resp.status_code == 201

    list_resp = client.get("/api/glossary")
    assert list_resp.status_code == 200
    terms = list_resp.json()
    assert any(t["source_term"] == "Claude" for t in terms)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_translation_api.py tests/test_glossary_api.py -v`
Expected: FAIL — routers don't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/translation.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.workers.translate import translate_task

router = APIRouter(prefix="/api/projects", tags=["translation"])


class JobRead(BaseModel):
    id: str
    project_id: str
    job_type: str
    status: str
    progress_pct: float
    current_step: str | None
    error_message: str | None

    class Config:
        from_attributes = True


class StartTranslateRequest(BaseModel):
    engine: str  # "gemini" | "openai"


class TranslationSegmentRead(BaseModel):
    id: str
    segment_id: str
    seq_index: int
    start_time: float
    end_time: float
    speaker_label: str
    source_text: str
    translated_text: str
    translated_text_edited: str | None


class TranslationSegmentUpdate(BaseModel):
    translated_text_edited: str


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/translate", response_model=JobRead, status_code=202)
def start_translate(
    project_id: str,
    payload: StartTranslateRequest,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = _get_owned_project(session, project_id, user_id)

    project.translate_engine = payload.engine
    project.status = "translating"
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)

    job = Job(project_id=project_id, job_type="translate")
    session.add(job)
    session.commit()
    session.refresh(job)

    translate_task.delay(project_id=project_id, engine_name=payload.engine)

    return job


@router.get("/{project_id}/translation", response_model=list[TranslationSegmentRead])
def get_translation(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    rows = session.exec(
        select(TranscriptSegment, TranslationSegment)
        .join(TranslationSegment, TranslationSegment.segment_id == TranscriptSegment.id)
        .where(TranscriptSegment.project_id == project_id)
        .order_by(TranscriptSegment.seq_index)
    ).all()

    return [
        TranslationSegmentRead(
            id=translation.id,
            segment_id=transcript.id,
            seq_index=transcript.seq_index,
            start_time=transcript.start_time,
            end_time=transcript.end_time,
            speaker_label=transcript.speaker_label,
            source_text=transcript.source_text_edited or transcript.source_text,
            translated_text=translation.translated_text,
            translated_text_edited=translation.translated_text_edited,
        )
        for transcript, translation in rows
    ]


@router.patch(
    "/{project_id}/translation/{translation_id}", response_model=TranslationSegmentRead
)
def update_translation_segment(
    project_id: str,
    translation_id: str,
    payload: TranslationSegmentUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    translation = session.get(TranslationSegment, translation_id)
    if translation is None:
        raise HTTPException(status_code=404, detail="Translation segment not found")
    transcript = session.get(TranscriptSegment, translation.segment_id)
    if transcript is None or transcript.project_id != project_id:
        raise HTTPException(status_code=404, detail="Translation segment not found")

    translation.translated_text_edited = payload.translated_text_edited
    session.add(translation)
    session.commit()
    session.refresh(translation)

    return TranslationSegmentRead(
        id=translation.id,
        segment_id=transcript.id,
        seq_index=transcript.seq_index,
        start_time=transcript.start_time,
        end_time=transcript.end_time,
        speaker_label=transcript.speaker_label,
        source_text=transcript.source_text_edited or transcript.source_text,
        translated_text=translation.translated_text,
        translated_text_edited=translation.translated_text_edited,
    )
```

```python
# backend/app/api/glossary.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.glossary_term import GlossaryTerm

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


class GlossaryTermCreate(BaseModel):
    source_term: str
    target_term: str


class GlossaryTermRead(BaseModel):
    id: str
    source_term: str
    target_term: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[GlossaryTermRead])
def list_glossary_terms(
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    return session.exec(select(GlossaryTerm).where(GlossaryTerm.user_id == user_id)).all()


@router.post("", response_model=GlossaryTermRead, status_code=201)
def create_glossary_term(
    payload: GlossaryTermCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    term = GlossaryTerm(user_id=user_id, **payload.model_dump())
    session.add(term)
    session.commit()
    session.refresh(term)
    return term
```

```python
# backend/app/main.py  (add to existing file)
from app.api.glossary import router as glossary_router
from app.api.translation import router as translation_router

app.include_router(translation_router)
app.include_router(glossary_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_translation_api.py tests/test_glossary_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/translation.py backend/app/api/glossary.py backend/app/main.py backend/tests/test_translation_api.py backend/tests/test_glossary_api.py
git commit -m "feat(backend): add translation and glossary endpoints"
```

---

### Task 6: Frontend — translate trigger + translation editor

**Files:**
- Create: `frontend/app/projects/[id]/translate/page.tsx`
- Create: `frontend/app/projects/[id]/translate/edit/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.test.ts`

**Interfaces:**
- Produces: `lib/api.ts` exports `startTranslate(projectId, engine)`, `getTranslation(projectId)`, `updateTranslationSegment(projectId, translationId, text)`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/lib/api.test.ts  (add)
it("startTranslate posts the chosen engine", async () => {
  const { startTranslate } = await import("./api");
  await startTranslate("proj-1", "openai");
  expect(fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/projects/proj-1/translate",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ engine: "openai" }),
    })
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `startTranslate` not exported.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/lib/types.ts  (append)
export interface TranslationSegment {
  id: string;
  segment_id: string;
  seq_index: number;
  start_time: number;
  end_time: number;
  speaker_label: string;
  source_text: string;
  translated_text: string;
  translated_text_edited: string | null;
}
```

```typescript
// frontend/lib/api.ts  (append)
import type { TranslationSegment } from "./types";

export async function startTranslate(projectId: string, engineName: "gemini" | "openai") {
  const res = await apiFetch(`/api/projects/${projectId}/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ engine: engineName }),
  });
  if (!res.ok) throw new Error("Failed to start translation");
  return res.json();
}

export async function getTranslation(projectId: string): Promise<TranslationSegment[]> {
  const res = await apiFetch(`/api/projects/${projectId}/translation`);
  if (!res.ok) throw new Error("Failed to load translation");
  return res.json();
}

export async function updateTranslationSegment(
  projectId: string,
  translationId: string,
  text: string
): Promise<TranslationSegment> {
  const res = await apiFetch(
    `/api/projects/${projectId}/translation/${translationId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ translated_text_edited: text }),
    }
  );
  if (!res.ok) throw new Error("Failed to update translation");
  return res.json();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Build the translate-trigger page (engine choice + progress)**

```typescript
// frontend/app/projects/[id]/translate/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { startTranslate } from "@/lib/api";
import { connectProjectWS } from "@/lib/ws";

interface ProgressMessage {
  status?: string;
  progress_pct?: number;
  error?: string;
}

export default function TranslatePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [engine, setEngine] = useState<"gemini" | "openai">("gemini");
  const [started, setStarted] = useState(false);
  const [progress, setProgress] = useState<ProgressMessage>({});

  useEffect(() => {
    const ws = connectProjectWS(id, (data) => {
      const message = data as ProgressMessage;
      setProgress(message);
      if (message.status === "done") {
        router.push(`/projects/${id}/translate/edit`);
      }
    });
    return () => ws.close();
  }, [id, router]);

  async function handleStart() {
    setStarted(true);
    await startTranslate(id, engine);
  }

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Dịch thuật</h1>

      {!started && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium">Chọn engine dịch</label>
            <select
              className="mt-1 w-full rounded border p-2"
              value={engine}
              onChange={(e) => setEngine(e.target.value as "gemini" | "openai")}
            >
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>
          <button onClick={handleStart} className="rounded bg-blue-600 px-4 py-2 text-white">
            Bắt đầu dịch
          </button>
        </div>
      )}

      {started && (
        <div className="space-y-2">
          <div className="h-3 w-full rounded bg-gray-200">
            <div
              className="h-3 rounded bg-blue-600 transition-all"
              style={{ width: `${progress.progress_pct ?? 0}%` }}
            />
          </div>
          <p className="text-sm text-gray-600">
            {progress.error ? `Lỗi: ${progress.error}` : "Đang dịch..."} (
            {progress.progress_pct ?? 0}%)
          </p>
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 6: Build the translation editor page**

```typescript
// frontend/app/projects/[id]/translate/edit/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getTranslation, updateTranslationSegment } from "@/lib/api";
import type { TranslationSegment } from "@/lib/types";

export default function TranslationEditPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [segments, setSegments] = useState<TranslationSegment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTranslation(id).then((data) => {
      setSegments(data);
      setLoading(false);
    });
  }, [id]);

  async function handleBlur(segment: TranslationSegment, newText: string) {
    const effectiveOriginal = segment.translated_text_edited ?? segment.translated_text;
    if (newText === effectiveOriginal) return;

    const updated = await updateTranslationSegment(id, segment.id, newText);
    setSegments((prev) => prev.map((s) => (s.id === segment.id ? updated : s)));
  }

  if (loading) return <p className="p-8">Đang tải...</p>;

  return (
    <main className="mx-auto max-w-4xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Chỉnh sửa bản dịch</h1>

      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 pr-4 w-1/3">Văn bản gốc</th>
            <th className="py-2">Bản dịch</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((segment) => (
            <tr key={segment.id} className="border-b align-top">
              <td className="py-2 pr-4 text-gray-500">{segment.source_text}</td>
              <td className="py-2">
                <textarea
                  className="w-full resize-none rounded border p-2"
                  defaultValue={segment.translated_text_edited ?? segment.translated_text}
                  onBlur={(e) => handleBlur(segment, e.target.value)}
                  rows={2}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button
        onClick={() => router.push(`/projects/${id}/voices`)}
        className="mt-6 rounded bg-blue-600 px-4 py-2 text-white"
      >
        Tiếp tục sang Chọn giọng đọc
      </button>
    </main>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/app/projects/ frontend/lib/api.ts frontend/lib/types.ts frontend/lib/api.test.ts
git commit -m "feat(frontend): add translation trigger and editor pages"
```

---

## Definition of Done for Phase 5

- [ ] `cd backend && pytest` passes (all Phase 1-5 tests).
- [ ] `cd frontend && npm test` passes.
- [ ] Manually: with real `GEMINI_API_KEY`/`OPENAI_API_KEY`, run translate on a transcribed project, watch progress complete, and confirm `translation_segments` rows exist and read naturally.
- [ ] Manually: add a glossary term, re-run translate, confirm the term is preserved untranslated in the output.
- [ ] Report back to the user with what was built, test output, and any deviations before starting Phase 6.
