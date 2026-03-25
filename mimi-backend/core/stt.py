"""Whisper 语音转文字模块"""

import numpy as np
import whisper
import yaml
from pathlib import Path


class SpeechToText:
    """使用 OpenAI Whisper 将音频转为文字"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        self.model_size = config["stt"]["model_size"]
        self.languages = config["stt"]["languages"]
        self.sample_rate = config["audio"]["sample_rate"]
        self.model = None

    def load_model(self):
        """加载 Whisper 模型（首次调用时）"""
        if self.model is None:
            print(f"正在加载 Whisper {self.model_size} 模型...")
            self.model = whisper.load_model(self.model_size)
            print("Whisper 模型加载完成")
        return self.model

    def transcribe_audio(self, audio_data: np.ndarray) -> dict:
        """
        转写音频数据

        Args:
            audio_data: numpy 数组，float32，采样率 16kHz

        Returns:
            {
                "text": "转写的文字",
                "language": "en" 或 "de",
                "segments": [{"start": 0.0, "end": 2.5, "text": "..."}]
            }
        """
        self.load_model()

        # 确保音频格式正确
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        # 如果是立体声，转为单声道
        if len(audio_data.shape) > 1:
            audio_data = audio_data.mean(axis=1)

        result = self.model.transcribe(
            audio_data,
            language=None,  # 自动检测语言
            task="transcribe",
        )

        return {
            "text": result["text"].strip(),
            "language": result.get("language", "unknown"),
            "segments": [
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"].strip(),
                }
                for seg in result.get("segments", [])
            ],
        }

    def transcribe_file(self, audio_path: str) -> dict:
        """
        转写音频文件

        Args:
            audio_path: 音频文件路径（支持 mp3, wav, m4a 等）

        Returns:
            同 transcribe_audio
        """
        self.load_model()
        result = self.model.transcribe(audio_path, language=None, task="transcribe")
        return {
            "text": result["text"].strip(),
            "language": result.get("language", "unknown"),
            "segments": [
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"].strip(),
                }
                for seg in result.get("segments", [])
            ],
        }
