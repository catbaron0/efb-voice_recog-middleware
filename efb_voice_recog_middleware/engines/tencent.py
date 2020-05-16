from typing import Dict
from io import BytesIO
from os import PathLike

import pydub
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import \
    TencentCloudSDKException
from tencentcloud.asr.v20190614 import asr_client, models
import base64

from . import SpeechEngine


class TencentSpeech(SpeechEngine):
    keys = None
    access_token = None
    engine_name = "Tencent"
    lang_list = ["zh", "en", "ca"]
    languages = {
        "zh": "16k",
        "en": "16k_en",
        "ca": "16k_ca"
    }

    def __init__(self, keys: Dict[str, str]):
        """
        Arguments:
            keys {Dict[str, str]} -- authorization keys
            requires "secret_id", "secret_key"
        """
        cred = credential.Credential(keys['secret_id'], keys['secret_key'])
        httpProfile = HttpProfile()
        httpProfile.endpoint = "asr.tencentcloudapi.com"
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        clientProfile.signMethod = "TC3-HMAC-SHA256"
        self.client = asr_client.AsrClient(cred, "ap-shanghai", clientProfile)
        self.lang = keys.get('lang', 'zh')

    def recognize(self, path: PathLike, lang: str = ""):
        if not lang:
            lang = self.lang
        if not isinstance(path, str):
            return ["ERROR!", "File must be a path string."]
        if lang not in self.lang_list:
            return ["ERROR!", "Invalid language."]

        try:
            with BytesIO() as f:
                f.seek(0)
                audio = pydub.AudioSegment.from_file(path)\
                    .set_frame_rate(16000)\
                    .set_channels(1)
                audio.export(f, format="wav", codec="s16le", bitrate='16k')

                # f.seek(0)

                # import pdb; pdb.set_trace()

                data = f.getvalue()
                data_len = len(data)
                # print(data_len)
                base64_wav = base64.b64encode(data).decode()

                req = models.SentenceRecognitionRequest()
                params = {"ProjectId": 0, "SubServiceType": 2, "EngSerViceType": self.languages[lang], "SourceType": 1, "Url": "",
                          "VoiceFormat": "wav", "UsrAudioKey": "catbaron.voice_recog", "Data": base64_wav, "DataLen": data_len}
                req._deserialize(params)
                resp = self.client.SentenceRecognition(req)
                # print(resp.to_json_string())
                return [resp.Result]
        except TencentCloudSDKException as err:
            return ["ERROR!", str(err)]
