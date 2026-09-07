import type { Project } from "./types";

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
