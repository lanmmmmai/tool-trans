"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getTranslation, updateTranslationSegment } from "@/lib/api";
import type { TranslationSegment } from "@/lib/types";

export default function TranslationEditPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [segments, setSegments] = useState<TranslationSegment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTranslation(id).then((data) => {
      setSegments(data);
      setLoading(false);
    });
  }, [id]);

  async function handleBlur(segment: TranslationSegment, newText: string) {
    const effectiveOriginal = segment.translated_text_edited ?? segment.translated_text;
    if (newText === effectiveOriginal) return;

    const updated = await updateTranslationSegment(id, segment.id, newText);
    setSegments((prev) => prev.map((s) => (s.id === segment.id ? updated : s)));
  }

  if (loading) return <p className="p-8">Đang tải...</p>;

  return (
    <main className="mx-auto max-w-4xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Chỉnh sửa bản dịch</h1>

      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 pr-4 w-1/3">Văn bản gốc</th>
            <th className="py-2">Bản dịch</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((segment) => (
            <tr key={segment.id} className="border-b align-top">
              <td className="py-2 pr-4 text-gray-500">{segment.source_text}</td>
              <td className="py-2">
                <textarea
                  className="w-full resize-none rounded border p-2"
                  defaultValue={segment.translated_text_edited ?? segment.translated_text}
                  onBlur={(e) => handleBlur(segment, e.target.value)}
                  rows={2}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button
        onClick={() => router.push(`/projects/${id}/voices`)}
        className="mt-6 rounded bg-blue-600 px-4 py-2 text-white"
      >
        Tiếp tục sang Chọn giọng đọc
      </button>
    </main>
  );
}
