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
});
