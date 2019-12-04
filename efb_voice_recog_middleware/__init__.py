# coding: utf-8
import base64
import logging
import os
import tempfile
import requests
import copy
import threading
import mimetypes
from io import BytesIO
from os import PathLike
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Any, Dict, Optional, List, BinaryIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml
import shutil

from ehforwarderbot import coordinator, EFBMiddleware, EFBMsg, MsgType, EFBChat
from ehforwarderbot.utils import get_config_path
from . import __version__ as version
from .engines.baidu import BaiduSpeech
from .engines.azure import AzureSpeech
from .engines.iflytek import IFlyTekSpeech
from .engines.tencent import TencentSpeech


class VoiceRecogMiddleware(EFBMiddleware):
    """
    EFB Middleware - Voice recognize middleware
    Convert voice mesage replied by user to text message.
    Author: Catbaron <https://github.com/catbaron>, 
            Eana Hufwe <https://1a23.com>
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
                BaiduSpeech(tokens['baidu'])
                )
        if "azure" in tokens:
            self.voice_engines.append(
                AzureSpeech(tokens['azure'])
            )
        if "iflytek" in tokens:
            self.voice_engines.append(
                IFlyTekSpeech(tokens['iflytek'])
            )
        if "tencent" in tokens:
            self.voice_engines.append(
                TencentSpeech(tokens['tencent'])
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

    def recognize(self, file: PathLike, lang: str) -> List[str]:
        '''
        Recognize the audio file to text.
        Args:
            file: An audio file. It should be FILE object in 'rb'
                  mode or string of path to the audio file.
        '''
        with ThreadPoolExecutor(max_workers=5) as exe:
            futures = {
                exe.submit(e.recognize, file, lang): (e.engine_name, lang)
                for e in self.voice_engines
            }
            results = []
            for future in as_completed(futures):
                engine_name, lang = futures[future]
                try:
                    data = future.result()
                    results.append(f'{engine_name} ({lang}): {"; ".join(data)}')
                except Exception as exc:
                    results.append(f'{engine_name} ({lang}): {repr(exc)}')
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

        if self.sent_by_master(message) and \
            message.text.startswith('recog`'):
            audio_msg = message.target
        elif not self.sent_by_master(message):
            audio_msg = message
        else:
            return message

        if not self.config.get('auto', True):
            return message

        if audio_msg.type != MsgType.Audio or \
            (audio_msg.edit and not audio_msg.edit_media) or \
            not audio_msg.file:
            return message

        if not self.voice_engines:
            return message

        audio: NamedTemporaryFile = NamedTemporaryFile(suffix=mimetypes.guess_extension(audio_msg.mime))
        shutil.copyfileobj(audio_msg.file, audio)
        audio.seek(0)
        audio_msg.file.seek(0)
        edited = copy.copy(audio_msg)

        threading.Thread(
            target=self.process_audio, 
            args=(edited, audio),
            name=f"VoiceRecog thread {audio_msg.uid}"
            ).start()

        return message
    
    def process_audio(self, message: EFBMsg, audio: NamedTemporaryFile):
        try:
            reply_text: str = '\n'.join(self.recognize(audio.name, self.lang))
        except Exception:
            reply_text = 'Failed to recognize voice content.'
        if getattr(message, 'text', None) is None:
            message.text = ""
        message.text += reply_text

        message.file = None
        message.edit = True
        message.edit_media = False
        coordinator.send_message(message)

        audio.close()
