from typing import Dict, TypeVar, Callable, Optional, List
from io import BytesIO
from os import PathLike

import pydub
import requests

from . import SpeechEngine

_T = TypeVar("_T")


class AzureSpeech(SpeechEngine):
    keys = None
    access_token = None
    engine_name = "Azure"
    lang_list = [
        "ar-EG", "ar-SA", "ar-AE", "ar-KW", "ar-QA", "ca-ES", "da-DK", "de-DE",
        "en-AU", "en-CA", "en-GB", "en-IN", "en-NZ", "en-US", "es-ES", "es-MX",
        "fi-FI", "fr-CA", "fr-FR", "gu-IN", "hi-IN", "it-IT", "ja-JP", "ko-KR",
        "mr-IN", "nb-NO", "nl-NL", "pl-PL", "pt-BR", "pt-PT", "ru-RU", "sv-SE",
        "ta-IN", "te-IN", "zh-CN", "zh-HK", "zh-TW", "th-TH", "tr-TR"
    ]

    @staticmethod
    def first(data: List[_T], key: Callable[[_T], bool]) -> Optional[_T]:
        """
        Look for first element in a list that matches a criteria.

        Args:
            data (list): List of elements
            key (function with one argument that returns Boolean value):
                Function to decide if an element matches the criteria.

        Returns:
            The first element found, or ``None``.
        """
        for i in data:
            if key(i):
                return i
        return None

    def __init__(self, keys: Dict[str, str]):
        """
        Arguments:
            keys {Dict[str, str]} -- authorization keys
            need 'key1' and 'endpoint'
        """
        self.key = keys['key1']
        self.auth_endpoint = keys['endpoint']
        self.endpoint = self.auth_endpoint.replace(
            '.api.cognitive.microsoft.com/sts/v1.0/issuetoken',
            '.stt.speech.microsoft.com/speech/recognition/'
            'conversation/cognitiveservices/v1'
        )
        self.lang = keys.get('lang', 'zh-CN')

    def recognize(self, path: PathLike, lang: str = ""):
        if not lang:
            lang = self.lang
        if not isinstance(path, str):
            return ["ERROR!", "File must be a path string."]
        if lang not in self.lang_list:
            lang = self.first(self.lang_list, lambda a: a.split(
                '-')[0] == lang.split('-')[0])
            if lang not in self.lang_list:
                return ["ERROR!", "Invalid language."]

        with BytesIO() as f:
            audio = pydub.AudioSegment.from_file(path)\
                .set_frame_rate(16000)\
                .set_channels(1)
            audio.export(
                f, format="ogg", codec="libopus", bitrate='16k')
            header = {
                "Ocp-Apim-Subscription-Key": self.key,
                "Content-Type": "audio/ogg; codecs=opus"
            }
            d = {
                "language": lang,
                "format": "detailed",
            }
            f.seek(0)
            r = requests.post(self.endpoint, params=d, data=f, headers=header)

            try:
                rjson = r.json()
            except ValueError:
                return ["ERROR!", r.text]

            if r.status_code == 200:
                return [i['Display'] for i in rjson['NBest']]
            else:
                return ["ERROR!", r.text]
