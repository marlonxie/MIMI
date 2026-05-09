"""共享对话历史。两路音频的 SentenceSegmenter 都往这里写完成的句子。"""

import json
import time
from datetime import datetime
from pathlib import Path


class SharedHistory:
    """共享的对话历史。两路音频的 SentenceSegmenter 都往这里写完成的句子。

    只负责：history 存储、context_window 查询、导出。
    不持有 pending 状态（那是 SentenceSegmenter 的事）。
    """

    def __init__(self, context_window_size: int = 10, export_path: str = "./transcripts"):
        self.context_window_size = context_window_size
        # expanduser 让 "~/Library/Application Support/MIMI/transcripts" 解析成绝对路径
        self.export_path = Path(export_path).expanduser()
        self.history: list[dict] = []  # 双路交织的完整对话记录
        self.start_time = time.time()

    def add_sentence(
        self, speaker: str, text: str, language: str, sentence_id: str | None = None
    ) -> dict:
        """添加一个完成的句子到 history。返回 entry dict。

        Args:
            sentence_id: 可选。传入则记到 entry["id"]，支持按 ID 反查（manual suggest）。
        """
        entry = {
            "speaker": speaker,
            "text": text,
            "language": language,
            "timestamp": self.current_timestamp(),
        }
        if sentence_id:
            entry["id"] = sentence_id
        self.history.append(entry)
        return entry

    def get_focused_context(self, sentence_id: str) -> tuple[str, str]:
        """按 ID 找句子，返回 (query, context)。

        query = 目标句文本
        context = 目标句之前最多 5 句（[Interviewer]/[Me] 前缀格式化）

        找不到返回 ("", "")。
        """
        for i, entry in enumerate(self.history):
            if entry.get("id") == sentence_id:
                query = entry["text"]
                start = max(0, i - 5)
                lines = []
                for e in self.history[start:i]:
                    label = "Interviewer" if e["speaker"] == "interviewer" else "Me"
                    lines.append(f"[{label}] {e['text']}")
                return query, "\n".join(lines)
        return "", ""

    def get_context_window(self, n: int = None) -> str:
        """返回最近 n 句对话，格式化为 LLM 可读的上下文。

        Returns:
            "[Interviewer] Tell me about your ML experience.\\n[Me] I worked on..."
        """
        if n is None:
            n = self.context_window_size
        recent = self.history[-n:] if len(self.history) > n else self.history
        lines = []
        for entry in recent:
            label = "Interviewer" if entry["speaker"] == "interviewer" else "Me"
            lines.append(f"[{label}] {entry['text']}")
        return "\n".join(lines)

    def has_new_interviewer_speech(self, since_index: int) -> bool:
        """检查从 since_index 之后是否有新的面试官发言"""
        for entry in self.history[since_index:]:
            if entry["speaker"] == "interviewer":
                return True
        return False

    def get_last_interviewer_text(self) -> str:
        """获取面试官最近说的完整内容（可能跨多句）"""
        texts = []
        for entry in reversed(self.history):
            if entry["speaker"] == "interviewer":
                texts.insert(0, entry["text"])
            else:
                break
        return " ".join(texts)

    def current_timestamp(self) -> str:
        """返回 hh:mm:ss 格式的当前会话时长"""
        elapsed = time.time() - self.start_time
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def export_transcript(self, output_path: str | None = None) -> str:
        """导出完整对话记录到文件。

        Args:
            output_path: 可选。UI（NSSavePanel）选定的绝对路径；None → 走 export_path 默认目录。
        """
        if output_path:
            # UI 选了具体路径，写到那
            filepath = Path(output_path).expanduser().resolve()
            filepath.parent.mkdir(parents=True, exist_ok=True)
        else:
            # CLI / 测试走默认目录
            self.export_path.mkdir(parents=True, exist_ok=True)
            filename = f"interview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = self.export_path / filename
        data = {
            "date": datetime.now().isoformat(),
            "duration_seconds": time.time() - self.start_time,
            "turns": len(self.history),
            "history": self.history,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(filepath)
