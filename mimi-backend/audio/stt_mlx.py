"""Whisper STT 模块 — 用 mlx-whisper 跑在 Apple Silicon Metal GPU + ANE 上

性能（M2 Pro, small 模型, 30s 音频）：
    - openai/whisper CPU: 10.21s
    - mlx-whisper Metal:  1.54s  ← 6.6x 加速
    - faster-whisper CPU: 6.89s
"""

import numpy as np
import yaml
import mlx_whisper
from pathlib import Path


class SpeechToText:
    """使用 mlx-whisper 在 Metal GPU 上跑 Whisper"""

    # config.yaml 的 model_size → mlx-community 仓库
    # 用 fp16 而不是 q4：实测 small 模型 fp16 和 q4 速度几乎相同（~1.1s for 30s audio）
    # 但 q4 量化更容易在 LocalAgreement-2 重复推理时产生 "the the the" 类幻觉
    MODEL_REPO_MAP = {
        "tiny":   "mlx-community/whisper-tiny-mlx",
        "base":   "mlx-community/whisper-base-mlx",
        "small":  "mlx-community/whisper-small-mlx",
        "medium": "mlx-community/whisper-medium-mlx",
        "large":  "mlx-community/whisper-large-v3-mlx",
    }

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        self.model_size = config["stt"]["model_size"]
        self.interview_language = config["user"]["interview_language"]
        self.sample_rate = config["audio"]["sample_rate"]

        if self.model_size not in self.MODEL_REPO_MAP:
            raise ValueError(
                f"不支持的 model_size: {self.model_size}, "
                f"可选: {list(self.MODEL_REPO_MAP.keys())}"
            )
        self.model_repo = self.MODEL_REPO_MAP[self.model_size]

    def load_model(self):
        """预热模型 — 第一次调用会下载权重 + Metal kernel 编译，约 30-60s。

        mlx-whisper 是 stateless 函数式 API，没有显式 model 对象。
        这里跑一次空音频触发缓存加载。
        """
        print(f"正在加载 mlx-whisper 模型: {self.model_repo}...")
        # 跑 0.5s 静音预热
        warmup_audio = np.zeros(int(self.sample_rate * 0.5), dtype=np.float32)
        try:
            mlx_whisper.transcribe(
                warmup_audio,
                path_or_hf_repo=self.model_repo,
                word_timestamps=False,
            )
        except Exception as e:
            print(f"模型预热警告（可忽略）: {e}")
        print("mlx-whisper 模型加载完成")
        return self.model_repo

    def transcribe_audio(self, audio_data: np.ndarray) -> dict:
        """转写音频数据。

        Args:
            audio_data: numpy 数组，float32，采样率 16kHz，单声道

        Returns:
            {
                "text": "转写的文字",
                "language": "en" 或 "de",
                "segments": [
                    {"start": 0.0, "end": 2.5, "text": "...",
                     "words": [{"word": "Hello", "start": 0.0, "end": 0.5}, ...]}
                ]
            }
        """
        # 确保音频格式正确
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)
        if len(audio_data.shape) > 1:
            audio_data = audio_data.mean(axis=1)

        result = mlx_whisper.transcribe(
            audio_data,
            path_or_hf_repo=self.model_repo,
            language=self.interview_language,  # None=自动检测（会幻觉成 Welsh），锁定=强制识别为该语言
            task="transcribe",
            word_timestamps=True,  # LocalAgreement-2 需要 word-level 时间戳
            condition_on_previous_text=False,  # 关闭跨段条件化，显著减少重复幻觉
            hallucination_silence_threshold=2.0,  # 静默 ≥2s 跳过 decode
        )

        return {
            "text": result["text"].strip(),
            "language": result.get("language", "unknown"),
            "segments": [
                {
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "text": seg["text"].strip(),
                    # streaming._drop_hallucinations 用这三个信号做后置过滤
                    "no_speech_prob": float(seg.get("no_speech_prob", 0.0)),
                    "avg_logprob": float(seg.get("avg_logprob", 0.0)),
                    "compression_ratio": float(seg.get("compression_ratio", 1.0)),
                    "words": [
                        {
                            "word": w["word"],
                            "start": float(w["start"]),
                            "end": float(w["end"]),
                        }
                        for w in seg.get("words", [])
                    ],
                }
                for seg in result.get("segments", [])
            ],
        }

    def set_interview_language(self, language: str | None) -> None:
        """运行时切换识别语言。下一次 transcribe_audio() 调用生效。

        Args:
            language: ISO 639-1 代码（"en" / "de" / ...）；None = 自动检测（不推荐）
        """
        self.interview_language = language

    def transcribe_file(self, audio_path: str) -> dict:
        """转写音频文件（路径或 numpy 数组都可以传给 mlx-whisper）"""
        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=self.model_repo,
            language=self.interview_language,
            task="transcribe",
            word_timestamps=True,
        )
        return {
            "text": result["text"].strip(),
            "language": result.get("language", "unknown"),
            "segments": [
                {
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "text": seg["text"].strip(),
                    "words": [
                        {
                            "word": w["word"],
                            "start": float(w["start"]),
                            "end": float(w["end"]),
                        }
                        for w in seg.get("words", [])
                    ],
                }
                for seg in result.get("segments", [])
            ],
        }
