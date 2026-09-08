"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getProjectVoices, setProjectVoices, startDub } from "@/lib/api";
import { connectProjectWS } from "@/lib/ws";

interface ProgressMessage {
  status?: string;
  progress_pct?: number;
  error?: string;
  can_retry_with_fallback?: boolean;
  failed_speaker?: string;
  failed_engine?: string;
}

export default function DubProgressPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [progress, setProgress] = useState<ProgressMessage>({});
  const [running, setRunning] = useState(false);

  useEffect(() => {
    const ws = connectProjectWS(id, (data) => {
      const message = data as ProgressMessage;
      setProgress(message);
      if (message.status === "done") {
        router.push(`/projects/${id}/preview`);
      }
    });
    return () => ws.close();
  }, [id, router]);

  async function handleStart() {
    setRunning(true);
    setProgress({});
    await startDub(id);
  }

  async function handleFallbackToGemini() {
    if (!progress.failed_speaker) return;
    const voices = await getProjectVoices(id);
    const updated = voices.map((v) =>
      v.speaker_label === progress.failed_speaker
        ? { ...v, engine: "gemini_tts", voice_id: "Kore" }
        : v
    );
    await setProjectVoices(id, updated);
    await handleStart();
  }

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Lồng tiếng</h1>

      {!running && (
        <button onClick={handleStart} className="rounded bg-blue-600 px-4 py-2 text-white">
          Bắt đầu lồng tiếng
        </button>
      )}

      {running && progress.status !== "failed" && (
        <div className="space-y-2">
          <div className="h-3 w-full rounded bg-gray-200">
            <div
              className="h-3 rounded bg-blue-600 transition-all"
              style={{ width: `${progress.progress_pct ?? 0}%` }}
            />
          </div>
          <p className="text-sm text-gray-600">Đang tạo giọng đọc... ({progress.progress_pct ?? 0}%)</p>
        </div>
      )}

      {progress.status === "failed" && (
        <div className="rounded border border-red-300 bg-red-50 p-4">
          <p className="mb-3 text-sm text-red-700">
            {progress.failed_engine === "edge_tts"
              ? `edge-tts gặp lỗi cho giọng của ${progress.failed_speaker}. Bạn có muốn chuyển sang Gemini TTS cho giọng này và thử lại không?`
              : `Lỗi: ${progress.error}`}
          </p>
          {progress.can_retry_with_fallback && (
            <button
              onClick={handleFallbackToGemini}
              className="rounded bg-blue-600 px-4 py-2 text-sm text-white"
            >
              Dùng Gemini TTS và thử lại
            </button>
          )}
        </div>
      )}
    </main>
  );
}
