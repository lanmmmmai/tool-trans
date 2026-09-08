from faster_whisper import WhisperModel

from app.services.stt.base import STTEngine, STTSegment


class WhisperLocalSTT(STTEngine):
    """No diarization — every segment is labelled 'speaker_1'. Used only as
    a fallback; ElevenLabs Scribe is the only engine that diarizes."""

    def __init__(self, model_size: str = "medium"):
        self.model_size = model_size
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio_path: str) -> list[STTSegment]:
        model = self._get_model()
        segments, _info = model.transcribe(audio_path, word_timestamps=False)
        return [
            STTSegment(
                start=seg.start,
                end=seg.end,
                speaker_label="speaker_1",
                text=seg.text.strip(),
                confidence=seg.avg_logprob,
            )
            for seg in segments
        ]
