import Link from "next/link";
import { listProjects } from "@/lib/api";

// Fetches per-user data (and will depend on the authenticated session once
// Phase 9 lands auth) — must never be statically prerendered at build time.
export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const projects = await listProjects();

  return (
    <main className="mx-auto max-w-3xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dự án của tôi</h1>
        <Link href="/projects/new" className="rounded bg-blue-600 px-4 py-2 text-white">
          + Dự án mới
        </Link>
      </div>

      {projects.length === 0 ? (
        <p className="text-gray-500">Chưa có dự án nào. Bắt đầu bằng cách tạo dự án mới.</p>
      ) : (
        <ul className="space-y-3">
          {projects.map((project) => (
            <li key={project.id} className="rounded border p-4">
              <div className="font-medium">{project.title}</div>
              <div className="text-sm text-gray-500">
                {project.source_language} → {project.target_language} · {project.status}
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
