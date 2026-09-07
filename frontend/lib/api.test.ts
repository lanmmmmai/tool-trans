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
});
