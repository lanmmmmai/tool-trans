from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class STTSegment:
    start: float
    end: float
    speaker_label: str
    text: str
    confidence: Optional[float] = None


class STTProviderError(Exception):
    pass


class STTEngine(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> list[STTSegment]:
        raise NotImplementedError
