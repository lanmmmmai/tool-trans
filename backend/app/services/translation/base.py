from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChunkSegment:
    seq_index: int
    text: str


@dataclass
class GlossaryEntry:
    source_term: str
    target_term: str


class TranslationProviderError(Exception):
    pass


def build_prompt(
    full_transcript: str,
    chunk: list[ChunkSegment],
    glossary: list[GlossaryEntry],
    target_language: str,
) -> str:
    glossary_lines = "\n".join(f"- {g.source_term} -> {g.target_term}" for g in glossary)
    numbered_chunk = "\n".join(f"{i + 1}. {seg.text}" for i, seg in enumerate(chunk))

    return f"""You are dubbing a YouTube/TikTok video into {target_language}.
Translate naturally and conversationally, as a native speaker would say it
out loud — not a stiff literal translation. Do NOT shorten or summarize;
preserve the full meaning of each sentence even if the translation ends up
longer or shorter than the original.

Full transcript for context (do not translate this block, it is only for
understanding pronouns/references):
---
{full_transcript}
---

Glossary — do NOT translate these terms, keep them exactly as-is:
{glossary_lines or "(none)"}

Translate ONLY the following {len(chunk)} numbered sentences into
{target_language}. Return a JSON array of exactly {len(chunk)} strings, in
the same order, with no numbering and no extra commentary — just the JSON
array.

{numbered_chunk}
"""


def strip_markdown_json_fence(text: str) -> str:
    """Some models wrap JSON output in ```json ... ``` fences even when
    told not to — strip them before parsing so callers don't need to."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        if stripped.endswith("```"):
            stripped = stripped[: -3]
        stripped = stripped.strip()
    return stripped


class Translator(ABC):
    @abstractmethod
    def translate_chunk(
        self,
        full_transcript: str,
        chunk: list[ChunkSegment],
        glossary: list[GlossaryEntry],
        target_language: str,
    ) -> list[str]:
        raise NotImplementedError
