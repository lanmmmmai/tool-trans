import { apiFetch } from "@/lib/api";

async function getHealth(): Promise<{ status: string } | null> {
  try {
    const res = await apiFetch("/health");
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export default async function HomePage() {
  const health = await getHealth();
  return (
    <main className="flex min-h-screen items-center justify-center">
      <p>
        Backend:{" "}
        {health?.status === "ok" ? "✅ đang hoạt động" : "❌ không kết nối được"}
      </p>
    </main>
  );
}
