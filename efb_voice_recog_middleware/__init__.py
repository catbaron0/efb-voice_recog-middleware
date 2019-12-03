# coding: utf-8
import base64
import logging
import os
import tempfile
import requests
import copy
import threading
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Any, Dict, Optional, List, BinaryIO

import yaml
import pydub
import shutil

from ehforwarderbot import coordinator, EFBMiddleware, EFBMsg, MsgType, EFBChat
from ehforwarderbot.utils import get_config_path
from . import __version__ as version
from abc import ABC, abstractmethod


class VoiceRecogMiddleware(EFBMiddleware):
    """
    EFB Middleware - Voice recognize middleware
    Convert voice mesage replied by user to text message.
    Author: Catbaron <https://github.com/catbaron>
    """

    middleware_id: str = "catbaron.voice_recog"
    middleware_name: str = "Voice Recognition Middleware"
    __version__ = version.__version__
    logger: logging.Logger = logging.getLogger(
        "plugins.%s.VoiceRecogMiddleware" % middleware_id)

    voice_engines: List = []

    def __init__(self, instance_id: str = None):
        super().__init__()
        self.config: Dict[str: Any] = self.load_config()
        tokens: Dict[str, Any] = self.config.get("speech_api", dict())
        self.lang: str = self.config.get('language', 'zh')

        if "baidu" in tokens:
            self.voice_engines.append(
                BaiduSpeech(channel=1, key_dict=tokens['baidu'])
                )
        if "azure" in tokens:
            self.voice_engines.append(
                AzureSpeech(channel=1, key_dict=tokens['azure'])
            )

    def load_config(self) -> Optional[Dict]:
        config_path: Path = get_config_path(self.middleware_id)
        if not config_path.exists():
            self.logger.info('The configure file does not exist!')
            return
        with config_path.open('r') as f:
            d: Dict[str, Any] = yaml.load(f)
            if not d:
                self.logger.info('Load configure file failed!')
                return
            return d

    def recognize(self, file: BinaryIO, lang: str) -> List[str]:
        '''
        Recognize the audio file to text.
        Args:
            file: An audio file. It should be FILE object in 'rb'
                  mode or string of path to the audio file.
        '''
        results = [f'{e.engine_name} ({lang}): {e.recognize(file, lang)}'
                   for e in self.voice_engines]
        return results

    @staticmethod
    def sent_by_master(message: EFBMsg) -> bool:
        return message.deliver_to == coordinator.master

    def process_message(self, message: EFBMsg) -> Optional[EFBMsg]:
        """
        Process a message with middleware
        Args:
            message (:obj:`.EFBMsg`): Message object to process
        Returns:
            Optional[:obj:`.EFBMsg`]: Processed message or None if discarded.
        """
        if self.sent_by_master(message) or message.type != MsgType.Audio:
            return message

        if not self.voice_engines:
            return message

        audio: BinaryIO = NamedTemporaryFile()
        shutil.copyfileobj(message.file, audio)
        audio.file.seek(0)
        message.file.file.seek(0)
        edited = copy.copy(EFBMsg)

        threading.Thread(
            target=self.process_audio, 
            args=(edit, audio), 
            name=f"VoiceRecog thread {message.uid}"
            ).start()

        return message
    
    def process_audio(self, message: EFBMsg, audio: BinaryIO):
        try:
            reply_text: str = '\n'.join(self.recognize(audio, self.lang))
        except Exception:
            reply_text = 'Failed to recognize voice content.'
            return message
        message.text += reply_text

        message.file = None
        message.edit = True
        message.edit_media = False
        coordinator.send_message(message)



class SpeechEngine(ABC):
    """Name of the speech recognition engine"""
    engine_name: str = __name__
    """List of languages codes supported"""
    lang_list: List[str] = []

    @abstractmethod
    def recognize(self, file: IO[bytes], lang: str):
        raise NotImplementedError()


class BaiduSpeech(SpeechEngine):
    key_dict: Dict[str, str] = None
    access_token: str = None
    full_token = None
    engine_name: str = "Baidu"
    lang_list = ['zh', 'ct', 'en']

    def __init__(self, channel: int, key_dict: Dict[str, str]):
        self.channel = channel
        self.key_dict = key_dict
        d = {
            "grant_type": "client_credentials",
            "client_id": key_dict['api_key'],
            "client_secret": key_dict['secret_key']
        }
        r = requests.post(
            "https://openapi.baidu.com/oauth/2.0/token",
            data=d
            ).json()
        self.access_token: str = r['access_token']
        self.full_token = r

    def recognize(self, file, lang):
        if hasattr(file, 'read'):
            pass
        elif isinstance(file, str):
            file = open(file, 'rb')
        else:
            return [
                "ERROR!", 
                "File must be a path string or a file object in `rb` mode."
                ]
        if lang.lower() not in self.lang_list:
            return ["ERROR!", "Invalid language."]

        audio = pydub.AudioSegment.from_file(file)
        audio = audio.set_frame_rate(16000)
        d = {
            "format": "pcm",
            "rate": 16000,
            "channel": self.channel,
            "cuid": "testing_user",
            "token": self.access_token,
            "lan": lang,
            "len": len(audio.raw_data),
            "speech": base64.b64encode(audio.raw_data).decode()
        }
        r = requests.post("http://vop.baidu.com/server_api", json=d)
        if r.status_code != 200:
            return [r.content, r]
        rjson = r.json()
        if rjson['err_no'] == 0:
            return [rjson['result']]
        else:
            return ["ERROR!", rjson['err_msg']]


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
    def first(data, key):
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

    def __init__(self, channel, keys):
        self.channel = channel
        self.key = keys['key1']
        self.auth_endpoint = keys['endpoint']
        self.endpoint = self.auth_endpoint.replace(
            '.api.cognitive.microsoft.com/sts/v1.0/issuetoken',
            '.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1'
        )

    def recognize(self, path, lang):
        if isinstance(path, str):
            file = open(path, 'rb')
        else:
            return ["ERROR!", "File must be a path string."]
        if lang not in self.lang_list:
            lang = self.first(self.lang_list, lambda a: a.split('-')[0] == lang.split('-')[0])
            if lang not in self.lang_list:
                return ["ERROR!", "Invalid language."]

        with BytesIO() as f:
            audio = pydub.AudioSegment.from_file(file)\
                .set_frame_rate(16000)\
                .set_channels(1)
            audio.export(f, format="ogg", codec="opus",
                         bitrate='16k', parameters=['-strict', '-2'])
            header = {
                "Ocp-Apim-Subscription-Key": self.key,
                "Content-Type": "audio/ogg; codecs=opus"
            }
            d = {
                "language": lang,
                "format": "detailed",
            }
            f.seek(0)
            r = requests.post(self.endpoint,
                              params=d, data=f, headers=header)

            try:
                rjson = r.json()
            except ValueError:
                return ["ERROR!", r.text, r]

            if r.status_code == 200:
                return [i['Display'] for i in rjson['NBest']]
            else:
                return ["ERROR!", r.text, r]
