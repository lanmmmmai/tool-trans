import json

from openai import OpenAI

from app.services.translation.base import (
    ChunkSegment,
    GlossaryEntry,
    Translator,
    TranslationProviderError,
    build_prompt,
    strip_markdown_json_fence,
)


class OpenAITranslator(Translator):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model

    def translate_chunk(
        self,
        full_transcript: str,
        chunk: list[ChunkSegment],
        glossary: list[GlossaryEntry],
        target_language: str,
    ) -> list[str]:
        prompt = build_prompt(full_transcript, chunk, glossary, target_language)
        client = OpenAI(api_key=self.api_key)

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise TranslationProviderError(f"OpenAI request failed: {exc}") from exc

        content = response.choices[0].message.content

        try:
            result = json.loads(strip_markdown_json_fence(content))
        except (json.JSONDecodeError, TypeError) as exc:
            raise TranslationProviderError(f"OpenAI returned non-JSON output: {exc}") from exc

        if not isinstance(result, list) or len(result) != len(chunk):
            raise TranslationProviderError(
                f"OpenAI returned {len(result) if isinstance(result, list) else 'invalid'} "
                f"items, expected {len(chunk)}"
            )
        return result
