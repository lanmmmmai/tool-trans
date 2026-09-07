# Phase 4: Transcript Editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user review and edit the transcript produced in Phase 3 — a sentence-list table (timestamp | speaker | source text | edit) — before translation starts.

**Architecture:** A `PATCH /api/projects/{id}/transcript/{segment_id}` endpoint that writes to `TranscriptSegment.source_text_edited` (the original `source_text` from STT is never overwritten, preserving the raw transcription for reference/debugging); a Next.js page rendering the segment list with inline-editable rows.

**Tech Stack:** FastAPI, SQLModel, Next.js.

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- Editor style is a sentence-list table for this version — no waveform/timeline editor (explicitly deferred, spec §9 Out of Scope).
- Users can edit transcript text (spec §Editing); they cannot edit timestamps or speaker assignment in this phase (speaker→voice mapping is Phase 6's concern; timestamp editing is not a requirement anywhere in the spec).
- Auth is still the Phase-2/3 stub (`get_current_user_id`).

## Established Interfaces (produced here, consumed by later phases)

- `PATCH /api/projects/{id}/transcript/{segment_id}` — body `{"source_text_edited": str}`, returns the updated `TranscriptSegmentRead` (schema from Phase 3).
- Downstream rule (used starting Phase 5's translation task): **the effective source text for any segment is `source_text_edited if source_text_edited is not None else source_text`.** This resolution rule is defined once here and referenced by name ("effective source text") in every later phase's plan instead of being re-derived.
- Frontend: `frontend/app/projects/[id]/transcript/edit/page.tsx` — the editor page linked to from Phase 3's progress page on completion.

---

### Task 1: `PATCH /transcript/{segment_id}` endpoint

**Files:**
- Modify: `backend/app/api/transcript.py`
- Create: `backend/tests/test_transcript_patch_api.py`

**Interfaces:**
- Produces: `PATCH /api/projects/{project_id}/transcript/{segment_id}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_transcript_patch_api.py
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.transcript_segment import TranscriptSegment

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
            "title": "Edit test",
            "source_language": "en",
            "target_language": "vi",
            "audio_mode": "ducking",
        },
    )
    return resp.json()["id"]


def test_patch_transcript_segment_sets_edited_text_without_touching_original():
    project_id = create_project()
    with Session(engine) as session:
        seg = TranscriptSegment(
            project_id=project_id, seq_index=0, start_time=0, end_time=1,
            speaker_label="speaker_1", source_text="Helo wrold",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)
        seg_id = seg.id

    resp = client.patch(
        f"/api/projects/{project_id}/transcript/{seg_id}",
        json={"source_text_edited": "Hello world"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_text_edited"] == "Hello world"
    assert body["source_text"] == "Helo wrold"


def test_patch_transcript_segment_404_for_wrong_project():
    project_id = create_project()
    resp = client.patch(
        f"/api/projects/{project_id}/transcript/does-not-exist",
        json={"source_text_edited": "x"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_transcript_patch_api.py -v`
Expected: FAIL — route doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/transcript.py  (append to the existing file)
class TranscriptSegmentUpdate(BaseModel):
    source_text_edited: str


@router.patch("/{project_id}/transcript/{segment_id}", response_model=TranscriptSegmentRead)
def update_transcript_segment(
    project_id: str,
    segment_id: str,
    payload: TranscriptSegmentUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    segment = session.get(TranscriptSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        raise HTTPException(status_code=404, detail="Segment not found")

    segment.source_text_edited = payload.source_text_edited
    session.add(segment)
    session.commit()
    session.refresh(segment)
    return segment
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_transcript_patch_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/transcript.py backend/tests/test_transcript_patch_api.py
git commit -m "feat(backend): add PATCH endpoint for editing transcript segments"
```

---

### Task 2: Frontend transcript editor page

**Files:**
- Create: `frontend/app/projects/[id]/transcript/edit/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.test.ts`

**Interfaces:**
- Produces: `lib/api.ts` exports `getTranscript(projectId: string): Promise<TranscriptSegment[]>`, `updateTranscriptSegment(projectId: string, segmentId: string, text: string): Promise<TranscriptSegment>`; `lib/types.ts` exports `TranscriptSegment`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/lib/api.test.ts  (add to the existing describe block)
it("updateTranscriptSegment PATCHes the segment with edited text", async () => {
  const { updateTranscriptSegment } = await import("./api");
  await updateTranscriptSegment("proj-1", "seg-1", "Fixed text");
  expect(fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/projects/proj-1/transcript/seg-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ source_text_edited: "Fixed text" }),
    })
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `updateTranscriptSegment` not exported.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/lib/types.ts  (append)
export interface TranscriptSegment {
  id: string;
  project_id: string;
  seq_index: number;
  start_time: number;
  end_time: number;
  speaker_label: string;
  source_text: string;
  source_text_edited: string | null;
  confidence: number | null;
}
```

```typescript
// frontend/lib/api.ts  (append)
import type { TranscriptSegment } from "./types";

export async function getTranscript(projectId: string): Promise<TranscriptSegment[]> {
  const res = await apiFetch(`/api/projects/${projectId}/transcript`);
  if (!res.ok) throw new Error("Failed to load transcript");
  return res.json();
}

export async function updateTranscriptSegment(
  projectId: string,
  segmentId: string,
  text: string
): Promise<TranscriptSegment> {
  const res = await apiFetch(`/api/projects/${projectId}/transcript/${segmentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_text_edited: text }),
  });
  if (!res.ok) throw new Error("Failed to update segment");
  return res.json();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Build the editor page**

```typescript
// frontend/app/projects/[id]/transcript/edit/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getTranscript, updateTranscriptSegment } from "@/lib/api";
import type { TranscriptSegment } from "@/lib/types";

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function TranscriptEditPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  useEffect(() => {
    getTranscript(id).then((data) => {
      setSegments(data);
      setLoading(false);
    });
  }, [id]);

  async function handleBlur(segment: TranscriptSegment, newText: string) {
    const effectiveOriginal = segment.source_text_edited ?? segment.source_text;
    if (newText === effectiveOriginal) return;

    setSavingId(segment.id);
    const updated = await updateTranscriptSegment(id, segment.id, newText);
    setSegments((prev) => prev.map((s) => (s.id === segment.id ? updated : s)));
    setSavingId(null);
  }

  if (loading) return <p className="p-8">Đang tải...</p>;

  return (
    <main className="mx-auto max-w-4xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Chỉnh sửa phiên âm</h1>

      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 pr-4">Thời gian</th>
            <th className="py-2 pr-4">Người nói</th>
            <th className="py-2">Văn bản</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((segment) => (
            <tr key={segment.id} className="border-b">
              <td className="py-2 pr-4 align-top text-gray-500">
                {formatTime(segment.start_time)}
              </td>
              <td className="py-2 pr-4 align-top text-gray-500">
                {segment.speaker_label}
              </td>
              <td className="py-2">
                <textarea
                  className="w-full resize-none rounded border p-2"
                  defaultValue={segment.source_text_edited ?? segment.source_text}
                  onBlur={(e) => handleBlur(segment, e.target.value)}
                  rows={2}
                />
                {savingId === segment.id && (
                  <span className="text-xs text-gray-400">Đang lưu...</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button
        onClick={() => router.push(`/projects/${id}/translate`)}
        className="mt-6 rounded bg-blue-600 px-4 py-2 text-white"
      >
        Tiếp tục sang Dịch thuật
      </button>
    </main>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/app/projects/ frontend/lib/api.ts frontend/lib/types.ts frontend/lib/api.test.ts
git commit -m "feat(frontend): add transcript editor page"
```

---

## Definition of Done for Phase 4

- [ ] `cd backend && pytest` passes (all Phase 1-4 tests).
- [ ] `cd frontend && npm test` passes.
- [ ] Manually: after a real transcription completes, open `/projects/{id}/transcript/edit`, edit a sentence, tab away, reload the page, and confirm the edit persisted.
- [ ] Report back to the user with what was built, test output, and any deviations before starting Phase 5.
