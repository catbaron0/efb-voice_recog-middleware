from typing import Dict, Any
from io import BytesIO
from os import PathLike
from datetime import datetime
import hmac
import hashlib
import base64
from time import mktime
from wsgiref.handlers import format_date_time
from urllib.parse import urlencode
import time
import json
from threading import Event, Thread

import pydub
import websocket

from . import SpeechEngine


STATUS_FIRST_FRAME = 0  # 第一帧的标识
STATUS_CONTINUE_FRAME = 1  # 中间帧标识
STATUS_LAST_FRAME = 2  # 最后一帧的标识


class IFlyTekSpeech(SpeechEngine):
    keys = None
    access_token = None
    engine_name = "IFlyTek"
    lang_list = ["zh_cn", "en_us", "zh", "en"]

    def __init__(self, keys: Dict[str, str]):
        """
        Arguments:
            keys {Dict[str, str]} -- authorization keys
            requires "app_id", "api_secret", "api_key"
        """
        self.keys = keys
        self.lang = keys.get('lang', 'zh_cn')

    class IFlyTekSession:

        languages = {
            "zh": "zh_cn",
            "en": "en_us"
        }

        def __init__(self, keys: Dict[str, str], file, lang):
            self.app_id = keys['app_id']
            self.api_secret = keys['api_secret']
            self.api_key = keys['api_key']
            self.common_args = {"app_id": self.app_id}
            self.done = Event()
            self.result = ""

            self.file = file
            self.lang = lang

            self.is_running = Event()
            self.ws = websocket.WebSocketApp(
                self.build_url(),
                on_open=self.on_start,
                on_message=self.on_message,
                on_error=self.on_error)

        def run(self):
            Thread(
                target=self.ws.run_forever,
                name="iflytek speech websocket listener thread"
            ).start()

            self.is_running.wait()

            self.send_file(self.file, self.lang)

            self.done.wait()

            self.ws.close()

            return self.result

        def build_url(self):
            """Create URL to websocket entrypoint with signature"""
            url = 'wss://ws-api.xfyun.cn/v2/iat'
            # 生成RFC1123格式的时间戳
            now = datetime.now()
            date = format_date_time(mktime(now.timetuple()))

            # 拼接字符串
            signature_origin = (
                "host: ws-api.xfyun.cn\n"
                f"date: {date}\n"
                "GET /v2/iat HTTP/1.1"
            )

            # 进行hmac-sha256进行加密
            signature_sha = hmac.new(
                self.api_secret.encode('utf-8'), 
                signature_origin.encode('utf-8'),
                digestmod=hashlib.sha256).digest()
            signature_sha = base64.b64encode(
                signature_sha).decode(encoding='utf-8')

            authorization_origin = (
                f'api_key="{self.api_key}", '
                'algorithm="hmac-sha256", '
                'headers="host date request-line", '
                f'signature="{signature_sha}"'
            )
            authorization = base64.b64encode(
                authorization_origin.encode('utf-8')).decode(encoding='utf-8')
            # 将请求的鉴权参数组合为字典
            v = {
                "authorization": authorization,
                "date": date,
                "host": "ws-api.xfyun.cn"
            }
            # 拼接鉴权参数，生成url
            url = url + '?' + urlencode(v)
            # print("date: ",date)
            # print("v: ",v)
            # 此处打印出建立连接时候的url,参考本demo的时候可取消上方打印的注释，比对相同参数时生成的url与自己代码生成的url是否一致
            # print('websocket url :', url)
            return url

        def get_business_args(self, lang: str) -> Dict[str, Any]:
            lang = self.languages.get(lang, lang)
            if lang == "zh_cn" or lang == "en_us":
                return {
                    "domain": "iat",
                    "language": lang,
                    "accent": "mandarin",
                    "vad_eos": 10000
                    }
            else:
                return {"domain": "iat", "language": lang, "vad_eos": 10000}

        def send_file(self, f, lang):
            frame_size = 8000  # 每一帧的音频大小
            interval = 0.04  # 发送音频间隔(单位:s)
            status = STATUS_FIRST_FRAME  # 音频的状态信息，标识音频是第一帧，还是中间帧、最后一帧

            biz_args = self.get_business_args(lang)

            while True:
                buf = f.read(frame_size)
                # 文件结束
                if not buf:
                    status = STATUS_LAST_FRAME
                # 第一帧处理
                # 发送第一帧音频，带business 参数
                # appid 必须带上，只需第一帧发送
                if status == STATUS_FIRST_FRAME:
                    d = {
                            "common": self.common_args,
                            "business": biz_args,
                            "data": {
                                "status": 0, "format": "audio/L16;rate=16000",
                                "audio": base64.b64encode(buf).decode(),
                                "encoding": "raw"
                            }
                        }
                    d = json.dumps(d)
                    self.ws.send(d)
                    status = STATUS_CONTINUE_FRAME
                # 中间帧处理
                elif status == STATUS_CONTINUE_FRAME:
                    d = {
                            "data": {
                                "status": 1, "format": "audio/L16;rate=16000",
                                "audio": base64.b64encode(buf).decode(),
                                "encoding": "raw"
                            }
                        }
                    self.ws.send(json.dumps(d))
                # 最后一帧处理
                elif status == STATUS_LAST_FRAME:
                    d = {
                            "data": {
                                "status": 2, "format": "audio/L16;rate=16000",
                                "audio": base64.b64encode(buf).decode(),
                                "encoding": "raw"
                            }
                        }
                    self.ws.send(json.dumps(d))
                    break
                # 模拟音频采样间隔
                time.sleep(interval)

        def on_start(self):
            self.is_running.set()

        def on_message(self, message):
            data = json.loads(message)
            code = data.get('code', -1)
            if code != 0:
                self.result += f"[Error: {data['message']}, {code}]"
                self.done.set()
                return

            self.result += ''.join(
                i['cw'][0]['w'] for i in data['data']['result']['ws']
                if i.get('cw')
            )
            if data['data']['status'] == 2:
                self.done.set()

        def on_error(self, error):
            self.result += f"[Error: {error}]"

    def recognize(self, path: PathLike, lang: str = ''):
        if not lang:
            lang = self.lang

        if not isinstance(path, str):
            return ["ERROR!", "File must be a path string."]
        if lang not in self.lang_list:
            return ["ERROR!", "Invalid language."]

        with BytesIO() as f:
            audio = pydub.AudioSegment.from_file(path)\
                .set_frame_rate(16000)\
                .set_channels(1)
            audio.export(f, format="s16le", codec="pcm_s16le", bitrate='16k')

            f.seek(0)

            return [self.IFlyTekSession(self.keys, f, lang).run()]
