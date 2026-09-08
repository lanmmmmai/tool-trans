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

  it("listProjects fetches from /api/projects", async () => {
    const { listProjects } = await import("./api");
    await listProjects();
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects",
      undefined
    );
  });

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

  it("setProjectVoices PUTs the assignment list", async () => {
    const { setProjectVoices } = await import("./api");
    const assignments = [
      { speaker_label: "speaker_1", engine: "edge_tts", voice_id: "vi-VN-HoaiMyNeural", speed: 1, pitch: 0 },
    ];
    await setProjectVoices("proj-1", assignments);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/projects/proj-1/voices",
      expect.objectContaining({ method: "PUT", body: JSON.stringify(assignments) })
    );
  });
});
