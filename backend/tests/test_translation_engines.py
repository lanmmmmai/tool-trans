import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.translation.base import ChunkSegment, GlossaryEntry, TranslationProviderError
from app.services.translation.gemini import GeminiTranslator
from app.services.translation.openai import OpenAITranslator


CHUNK = [ChunkSegment(seq_index=0, text="Hello"), ChunkSegment(seq_index=1, text="World")]
GLOSSARY = [GlossaryEntry(source_term="Claude", target_term="Claude")]


def test_gemini_translator_parses_json_array_response():
    translator = GeminiTranslator(api_key="fake")

    with patch("app.services.translation.gemini.genai.Client") as MockClient:
        mock_client = MockClient.return_value
        mock_response = MagicMock()
        mock_response.text = json.dumps(["Xin chào", "Thế giới"])
        mock_client.models.generate_content.return_value = mock_response

        result = translator.translate_chunk(
            full_transcript="Hello World", chunk=CHUNK, glossary=GLOSSARY, target_language="vi"
        )

    assert result == ["Xin chào", "Thế giới"]


def test_gemini_translator_raises_on_mismatched_count():
    translator = GeminiTranslator(api_key="fake")

    with patch("app.services.translation.gemini.genai.Client") as MockClient:
        mock_client = MockClient.return_value
        mock_response = MagicMock()
        mock_response.text = json.dumps(["Only one"])
        mock_client.models.generate_content.return_value = mock_response

        with pytest.raises(TranslationProviderError):
            translator.translate_chunk(
                full_transcript="Hello World", chunk=CHUNK, glossary=GLOSSARY, target_language="vi"
            )


def test_openai_translator_parses_json_array_response():
    translator = OpenAITranslator(api_key="fake")

    with patch("app.services.translation.openai.OpenAI") as MockOpenAI:
        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = json.dumps(["Xin chào", "Thế giới"])
        mock_client.chat.completions.create.return_value.choices = [
            MagicMock(message=mock_message)
        ]

        result = translator.translate_chunk(
            full_transcript="Hello World", chunk=CHUNK, glossary=GLOSSARY, target_language="vi"
        )

    assert result == ["Xin chào", "Thế giới"]
