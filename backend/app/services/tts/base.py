from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VoiceCatalogEntry:
    voice_id: str
    name: str
    gender: str
    engine: str


class TTSProviderError(Exception):
    pass


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice_id: str, speed: float, out_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_voices(self) -> list[VoiceCatalogEntry]:
        raise NotImplementedError
