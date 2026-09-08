import type {
  Project,
  TranscriptSegment,
  TranslationSegment,
  VoiceAssignment,
  VoiceCatalogEntry,
} from "./types";

function getApiBase(): string {
  // Server-side (SSR / Server Components) runs inside the frontend
  // container, where "localhost" resolves to itself, not the backend
  // container — it must use the Docker network's service name instead.
  // The browser (client-side) has no such container, so it always uses
  // the publicly reachable NEXT_PUBLIC_API_URL.
  if (typeof window === "undefined") {
    return process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const base = getApiBase();
  return fetch(`${base}${path}`, init);
}

export async function listProjects(): Promise<Project[]> {
  const res = await apiFetch("/api/projects");
  if (!res.ok) throw new Error("Failed to load projects");
  return res.json();
}

export async function createProject(input: {
  title: string;
  source_language: string;
  target_language: string;
  audio_mode: string;
}): Promise<Project> {
  const res = await apiFetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error("Failed to create project");
  return res.json();
}

export async function uploadVideo(projectId: string, file: File): Promise<void> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await apiFetch(`/api/projects/${projectId}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Failed to upload video");
}

export async function importVideoFromUrl(projectId: string, url: string): Promise<void> {
  const res = await apiFetch(`/api/projects/${projectId}/import-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error("Failed to import video");
}

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

export async function getVoiceCatalog(): Promise<VoiceCatalogEntry[]> {
  const res = await apiFetch("/api/voices/catalog");
  if (!res.ok) throw new Error("Failed to load voice catalog");
  return res.json();
}

export function previewVoiceUrl(engine: string, voiceId: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}/api/voices/preview?engine=${encodeURIComponent(engine)}&voice_id=${encodeURIComponent(voiceId)}`;
}

export async function getProjectVoices(projectId: string): Promise<VoiceAssignment[]> {
  const res = await apiFetch(`/api/projects/${projectId}/voices`);
  if (!res.ok) throw new Error("Failed to load project voices");
  return res.json();
}

export async function setProjectVoices(
  projectId: string,
  assignments: VoiceAssignment[]
): Promise<VoiceAssignment[]> {
  const res = await apiFetch(`/api/projects/${projectId}/voices`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(assignments),
  });
  if (!res.ok) throw new Error("Failed to save voice assignment");
  return res.json();
}

export async function startDub(projectId: string) {
  const res = await apiFetch(`/api/projects/${projectId}/dub`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to start dubbing");
  return res.json();
}
