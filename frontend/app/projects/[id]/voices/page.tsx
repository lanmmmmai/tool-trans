"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getTranscript, getVoiceCatalog, previewVoiceUrl, setProjectVoices } from "@/lib/api";
import type { VoiceAssignment, VoiceCatalogEntry } from "@/lib/types";

export default function VoiceSelectionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [catalog, setCatalog] = useState<VoiceCatalogEntry[]>([]);
  const [assignments, setAssignments] = useState<VoiceAssignment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const [transcript, voiceCatalog] = await Promise.all([
        getTranscript(id),
        getVoiceCatalog(),
      ]);

      const speakers = Array.from(new Set(transcript.map((t) => t.speaker_label)));
      const edgeVoices = voiceCatalog.filter((v) => v.engine === "edge_tts");

      setCatalog(voiceCatalog);
      setAssignments(
        speakers.map((speaker, i) => ({
          speaker_label: speaker,
          engine: "edge_tts",
          voice_id: edgeVoices[i % edgeVoices.length]?.voice_id ?? edgeVoices[0]?.voice_id ?? "",
          speed: 1.0,
          pitch: 0.0,
        }))
      );
      setLoading(false);
    }
    load();
  }, [id]);

  function updateAssignment(index: number, patch: Partial<VoiceAssignment>) {
    setAssignments((prev) =>
      prev.map((a, i) => (i === index ? { ...a, ...patch } : a))
    );
  }

  async function handleContinue() {
    await setProjectVoices(id, assignments);
    router.push(`/projects/${id}/dub`);
  }

  if (loading) return <p className="p-8">Đang tải...</p>;

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Chọn giọng đọc</h1>

      <div className="space-y-6">
        {assignments.map((assignment, index) => (
          <div key={assignment.speaker_label} className="rounded border p-4">
            <div className="mb-2 font-medium">{assignment.speaker_label}</div>

            <div className="grid grid-cols-2 gap-3">
              <select
                className="rounded border p-2"
                value={assignment.voice_id}
                onChange={(e) => {
                  const voice = catalog.find((v) => v.voice_id === e.target.value);
                  updateAssignment(index, {
                    voice_id: e.target.value,
                    engine: voice?.engine ?? assignment.engine,
                  });
                }}
              >
                {catalog.map((v) => (
                  <option key={`${v.engine}-${v.voice_id}`} value={v.voice_id}>
                    {v.name} ({v.engine === "edge_tts" ? "edge-tts" : "Gemini TTS"})
                  </option>
                ))}
              </select>

              <audio
                controls
                src={previewVoiceUrl(assignment.engine, assignment.voice_id)}
                className="h-9"
              />
            </div>

            <div className="mt-2 flex items-center gap-2 text-sm">
              <label>Tốc độ</label>
              <input
                type="range"
                min="0.7"
                max="1.3"
                step="0.05"
                value={assignment.speed}
                onChange={(e) => updateAssignment(index, { speed: Number(e.target.value) })}
              />
              <span>{assignment.speed.toFixed(2)}x</span>
            </div>
          </div>
        ))}
      </div>

      <button
        onClick={handleContinue}
        className="mt-6 rounded bg-blue-600 px-4 py-2 text-white"
      >
        Tiếp tục sang Lồng tiếng
      </button>
    </main>
  );
}
