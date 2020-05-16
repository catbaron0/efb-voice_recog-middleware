from typing import Dict
from io import BytesIO

import pydub
import requests

from . import SpeechEngine


class BaiduSpeech(SpeechEngine):
    key_dict: Dict[str, str] = None
    access_token: str = None
    full_token = None
    engine_name: str = "Baidu"
    lang_list = [
        'zh', 'en', 'zh-yue', 'zh-x-en',
        'zh-x-sichuan', 'zh-x-farfield']

    languages = {
        "zh": 1537,
        "zh-x-en": 1536,
        "en": 1737,
        "ct": 1637,  # for compatibility
        "zh-yue": 1637,
        "zh-x-sichuan": 1837,
        "zh-x-farfield": 1936
    }

    def __init__(self, key_dict: Dict[str, str]):
        self.key_dict = key_dict
        self.lang = key_dict.get('lang', 'zh')
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

    def recognize(self, file, lang=""):
        if not lang:
            lang = self.lang
        if hasattr(file, 'read'):
            pass
        elif not isinstance(file, str):
            return [
                "ERROR!",
                "File must be a path string or a file object in `rb` mode."
            ]
        if lang.lower() not in self.lang_list:
            return ["ERROR!", "Invalid language."]

        audio = pydub.AudioSegment.from_file(
            file).set_frame_rate(16000).set_channels(1)
        with BytesIO() as f:
            audio.export(f, format="s16le", codec="pcm_s16le")
            headers = {
                "Content-Type": "audio/pcm;rate=16000"
            }
            params = {
                "cuid": "catbaron.voice_recog",
                "token": self.access_token,
                "dev_pid": self.languages[lang],
            }
            r = requests.post("http://vop.baidu.com/server_api",
                              params=params, headers=headers, data=f)
            if r.status_code != 200:
                return ["ERROR!", r.status_code, r.content]
            rjson = r.json()
            if rjson['err_no'] == 0:
                return rjson['result']
            else:
                return ["ERROR!", rjson['err_msg']]
