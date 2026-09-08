import json

from google import genai

from app.services.translation.base import (
    ChunkSegment,
    GlossaryEntry,
    Translator,
    TranslationProviderError,
    build_prompt,
    strip_markdown_json_fence,
)


class GeminiTranslator(Translator):
    def __init__(self, api_key: str, model: str = "gemini-3.6-flash"):
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
        client = genai.Client(api_key=self.api_key)

        try:
            response = client.models.generate_content(model=self.model, contents=prompt)
        except Exception as exc:
            raise TranslationProviderError(f"Gemini request failed: {exc}") from exc

        try:
            result = json.loads(strip_markdown_json_fence(response.text))
        except (json.JSONDecodeError, TypeError) as exc:
            raise TranslationProviderError(f"Gemini returned non-JSON output: {exc}") from exc

        if not isinstance(result, list) or len(result) != len(chunk):
            raise TranslationProviderError(
                f"Gemini returned {len(result) if isinstance(result, list) else 'invalid'} "
                f"items, expected {len(chunk)}"
            )
        return result
