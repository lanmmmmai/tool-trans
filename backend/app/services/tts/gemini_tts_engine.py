import wave

from google import genai
from google.genai import types

from app.services.tts.base import TTSEngine, TTSProviderError, VoiceCatalogEntry

VOICE_CATALOG = [
    VoiceCatalogEntry(voice_id="Kore", name="Kore", gender="female", engine="gemini_tts"),
    VoiceCatalogEntry(voice_id="Puck", name="Puck", gender="male", engine="gemini_tts"),
    VoiceCatalogEntry(voice_id="Charon", name="Charon", gender="male", engine="gemini_tts"),
    VoiceCatalogEntry(voice_id="Leda", name="Leda", gender="female", engine="gemini_tts"),
]

MODEL_NAME = "gemini-3.1-flash-tts-preview"
SAMPLE_RATE_HZ = 24000


class GeminiTTSEngine(TTSEngine):
    """Gemini TTS has no numeric speed/rate parameter — speed is applied as
    a best-effort natural-language instruction, per the spec's documented
    caveat that Gemini TTS cannot hit an exact target duration."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def synthesize(self, text: str, voice_id: str, speed: float, out_path: str) -> None:
        pace_hint = ""
        if speed > 1.05:
            pace_hint = " (a bit faster than normal pace)"
        elif speed < 0.95:
            pace_hint = " (a bit slower than normal pace)"

        # Bare text is sometimes interpreted as a chat prompt rather than a
        # dictation request (confirmed for real: it can reply with text
        # instead of audio) — an explicit "say this aloud" framing avoids
        # that ambiguity.
        prompt = f"Say the following text aloud exactly as written{pace_hint}: {text}"

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_id)
                        )
                    ),
                ),
            )
            content = response.candidates[0].content
            if content is None or not content.parts:
                raise TTSProviderError(
                    f"Gemini TTS returned no audio content for voice {voice_id} "
                    "(model may have responded with text instead of audio)"
                )
            pcm_data = content.parts[0].inline_data.data
        except TTSProviderError:
            raise
        except Exception as exc:
            raise TTSProviderError(f"Gemini TTS failed for voice {voice_id}: {exc}") from exc

        with wave.open(out_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE_HZ)
            wav_file.writeframes(pcm_data)

    def list_voices(self) -> list[VoiceCatalogEntry]:
        return VOICE_CATALOG
