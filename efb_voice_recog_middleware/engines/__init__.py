from abc import ABC, abstractmethod
from typing import IO, List


class SpeechEngine(ABC):
    """Name of the speech recognition engine"""
    engine_name: str = __name__
    """List of languages codes supported"""
    lang_list: List[str] = []

    @abstractmethod
    def recognize(self, file: IO[bytes], lang: str):
        raise NotImplementedError()
