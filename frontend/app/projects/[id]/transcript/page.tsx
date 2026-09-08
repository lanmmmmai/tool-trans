"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { connectProjectWS } from "@/lib/ws";

interface ProgressMessage {
  status?: string;
  step?: string;
  progress_pct?: number;
  error?: string;
}

export default function TranscriptProgressPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [started, setStarted] = useState(false);
  const [progress, setProgress] = useState<ProgressMessage>({});

  useEffect(() => {
    const ws = connectProjectWS(id, (data) => {
      const message = data as ProgressMessage;
      setProgress(message);
      if (message.status === "done") {
        router.push(`/projects/${id}/transcript/edit`);
      }
    });
    return () => ws.close();
  }, [id, router]);

  async function startTranscribe() {
    setStarted(true);
    await apiFetch(`/api/projects/${id}/transcribe`, { method: "POST" });
  }

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Nhận diện lời nói</h1>

      {!started && (
        <button
          onClick={startTranscribe}
          className="rounded bg-blue-600 px-4 py-2 text-white"
        >
          Bắt đầu nhận diện
        </button>
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
            {progress.error
              ? `Lỗi: ${progress.error}`
              : progress.step ?? "Đang chờ..."}{" "}
            ({progress.progress_pct ?? 0}%)
          </p>
        </div>
      )}
    </main>
  );
}
