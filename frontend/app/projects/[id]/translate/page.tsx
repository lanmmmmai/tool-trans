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
