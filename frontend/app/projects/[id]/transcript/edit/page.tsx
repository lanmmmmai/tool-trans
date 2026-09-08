"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getTranscript, updateTranscriptSegment } from "@/lib/api";
import type { TranscriptSegment } from "@/lib/types";

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function TranscriptEditPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  useEffect(() => {
    getTranscript(id).then((data) => {
      setSegments(data);
      setLoading(false);
    });
  }, [id]);

  async function handleBlur(segment: TranscriptSegment, newText: string) {
    const effectiveOriginal = segment.source_text_edited ?? segment.source_text;
    if (newText === effectiveOriginal) return;

    setSavingId(segment.id);
    const updated = await updateTranscriptSegment(id, segment.id, newText);
    setSegments((prev) => prev.map((s) => (s.id === segment.id ? updated : s)));
    setSavingId(null);
  }

  if (loading) return <p className="p-8">Đang tải...</p>;

  return (
    <main className="mx-auto max-w-4xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Chỉnh sửa phiên âm</h1>

      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 pr-4">Thời gian</th>
            <th className="py-2 pr-4">Người nói</th>
            <th className="py-2">Văn bản</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((segment) => (
            <tr key={segment.id} className="border-b">
              <td className="py-2 pr-4 align-top text-gray-500">
                {formatTime(segment.start_time)}
              </td>
              <td className="py-2 pr-4 align-top text-gray-500">
                {segment.speaker_label}
              </td>
              <td className="py-2">
                <textarea
                  className="w-full resize-none rounded border p-2"
                  defaultValue={segment.source_text_edited ?? segment.source_text}
                  onBlur={(e) => handleBlur(segment, e.target.value)}
                  rows={2}
                />
                {savingId === segment.id && (
                  <span className="text-xs text-gray-400">Đang lưu...</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button
        onClick={() => router.push(`/projects/${id}/translate`)}
        className="mt-6 rounded bg-blue-600 px-4 py-2 text-white"
      >
        Tiếp tục sang Dịch thuật
      </button>
    </main>
  );
}
