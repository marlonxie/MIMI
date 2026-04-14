"""说话人识别模块。

当前逻辑（简化版）：
    系统音频（ScreenCaptureKit）→ "interviewer"
    麦克风（AVAudioEngine）→ "me"

前端在音频 binary 数据前加 1 字节标记：
    0x00 = 系统音频 → "interviewer"
    0x01 = 麦克风   → "me"

未来扩展方向：
    - Speaker diarization（声纹模型，区分多个面试官）
    - Voice Activity Detection（更精确的说话人检测）
    - 声纹注册（面试前录一段自己的声音作为参考）
"""

# 音频源前缀字节 → speaker 标签
SOURCE_PREFIX_MAP = {
    0x00: "interviewer",  # 系统音频（ScreenCaptureKit）
    0x01: "me",           # 麦克风（AVAudioEngine）
}

# speaker 标签 → 前端显示名称
SPEAKER_LABELS = {
    "interviewer": "面试官",
    "me": "我",
}


def identify_speaker(source_byte: int) -> str:
    """根据音频源前缀字节返回 speaker 标签。

    Args:
        source_byte: 前端发送的 1 字节标记（0x00 或 0x01）

    Returns:
        "interviewer" 或 "me"
    """
    return SOURCE_PREFIX_MAP.get(source_byte, "interviewer")
