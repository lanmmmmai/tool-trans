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
