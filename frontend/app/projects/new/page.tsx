"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createProject, importVideoFromUrl, uploadVideo } from "@/lib/api";

const SOURCE_LANGUAGES = [
  { value: "en", label: "Tiếng Anh" },
  { value: "zh", label: "Tiếng Trung" },
  { value: "ja", label: "Tiếng Nhật" },
];

const AUDIO_MODES = [
  { value: "silent", label: "Chỉ giọng mới (im lặng nền)" },
  { value: "music_separated", label: "Giữ nhạc nền (tách bằng Demucs)" },
  { value: "ducking", label: "Giảm âm nền (ducking)" },
];

export default function NewProjectPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState("en");
  const [audioMode, setAudioMode] = useState("ducking");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const project = await createProject({
        title,
        source_language: sourceLanguage,
        target_language: "vi",
        audio_mode: audioMode,
      });

      if (file) {
        await uploadVideo(project.id, file);
      } else if (url) {
        await importVideoFromUrl(project.id, url);
      } else {
        throw new Error("Vui lòng chọn file hoặc dán link");
      }

      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Có lỗi xảy ra");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Tạo dự án mới</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium">Tên dự án</label>
          <input
            className="mt-1 w-full rounded border p-2"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium">Ngôn ngữ nguồn</label>
          <select
            className="mt-1 w-full rounded border p-2"
            value={sourceLanguage}
            onChange={(e) => setSourceLanguage(e.target.value)}
          >
            {SOURCE_LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium">Chế độ âm thanh</label>
          <select
            className="mt-1 w-full rounded border p-2"
            value={audioMode}
            onChange={(e) => setAudioMode(e.target.value)}
          >
            {AUDIO_MODES.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium">Tải file video lên</label>
          <input
            type="file"
            accept="video/*"
            className="mt-1 w-full"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>

        <div className="text-center text-sm text-gray-400">— hoặc —</div>

        <div>
          <label className="block text-sm font-medium">Dán link YouTube/TikTok</label>
          <input
            type="url"
            className="mt-1 w-full rounded border p-2"
            placeholder="https://..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-blue-600 py-2 text-white disabled:opacity-50"
        >
          {submitting ? "Đang tạo..." : "Tạo dự án"}
        </button>
      </form>
    </main>
  );
}
