"""LLM provider 翻译质量 + 延迟对比脚本.

对比 gemini (云端 API baseline) vs ollama qwen3:8b (本地 llama.cpp+Metal).

测量:
  - 单调用 e2e 延迟 (translate_async)
  - 单调用首字延迟 TTFT (translate_stream 取首个非空 chunk)
  - 与 Whisper 并发时的翻译延迟

跑法:
    cd mimi-backend
    /Users/marlon/anaconda3/envs/mimi/bin/python scripts/bench_llm.py
"""

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from llm import LLMManager
from translation.langchain_translator import Translator


FIXTURES = [
    {
        "label": "tech_question",
        "text": "Tell me about a time when you had to deal with a difficult colleague.",
        "lang": "en",
        "context": "",
    },
    {
        "label": "tech_terms",
        "text": "I have three years of experience with React, TypeScript and Kubernetes.",
        "lang": "en",
        "context": "",
    },
    {
        "label": "german",
        "text": "Erzählen Sie mir von Ihren Stärken und Schwächen.",
        "lang": "de",
        "context": "",
    },
    {
        "label": "short_response",
        "text": "OK.",
        "lang": "en",
        "context": "[Interviewer] We use microservices with gRPC.\n[Me] I'm familiar with that.",
    },
    {
        "label": "fillers",
        "text": "Um, uh, like, you know.",
        "lang": "en",
        "context": "",
    },
    {
        "label": "mixed_lang_ctx",
        "text": "Great. Can you walk me through a component you built?",
        "lang": "en",
        "context": "[Interviewer] 你用过 React 吗？\n[Me] 用过，做过几个前端项目。",
    },
    {
        "label": "long_with_filler",
        "text": "Um, so I would say I have like three years of experience with, uh, distributed systems and Kubernetes orchestration.",
        "lang": "en",
        "context": "",
    },
]

OUTPUT_PATH = Path(__file__).parent / "bench_llm_output.jsonl"
N_RUNS = 2  # warmup 之后每个 fixture 跑 N_RUNS 次取均值

# 测试配置：(label, provider, model_override). model=None 则用 PROVIDER_MAP 默认
CONFIGS: list[tuple[str, str, str | None]] = [
    ("gemini", "gemini", None),
    ("ollama-8b-hybrid", "ollama", "qwen3:8b"),
    ("ollama-4b-instruct-2507", "ollama", "qwen3:4b-instruct-2507-q4_K_M"),
]


def make_translator(provider: str, model: str | None = None) -> Translator:
    return Translator(LLMManager(default_provider=provider, default_model=model))


async def measure_e2e(translator: Translator, fix: dict) -> tuple[float, str]:
    t0 = time.perf_counter()
    result = await translator.translate_async(
        fix["text"], source_language=fix["lang"], context=fix["context"]
    )
    elapsed = (time.perf_counter() - t0) * 1000
    return elapsed, result["translation"]


async def measure_ttft(translator: Translator, fix: dict) -> tuple[float, float, str]:
    """流式翻译，返回 (ttft_ms, total_ms, full_text)."""
    t0 = time.perf_counter()
    ttft = None
    chunks = []
    async for chunk in translator.translate_stream(
        fix["text"], source_language=fix["lang"], context=fix["context"]
    ):
        if ttft is None and chunk:
            ttft = (time.perf_counter() - t0) * 1000
        chunks.append(chunk)
    total = (time.perf_counter() - t0) * 1000
    return (ttft if ttft is not None else total), total, "".join(chunks)


async def bench_config(label: str, provider: str, model: str | None) -> dict:
    print(f"\n{'='*78}\n[{label}] 翻译延迟测试 (provider={provider} model={model or 'default'})\n{'='*78}")
    try:
        translator = make_translator(provider, model)
    except Exception as e:
        print(f"  构造 translator 失败: {e}")
        return {}
    if not translator.is_ready:
        print(f"  {label} 未就绪 (缺 key 或加载失败)")
        return {}

    print(f"  warmup ...")
    try:
        await measure_e2e(translator, FIXTURES[0])
        await measure_ttft(translator, FIXTURES[0])
    except Exception as e:
        print(f"  warmup 失败: {e}")
        return {}

    rows = []
    for fix in FIXTURES:
        e2e_runs: list[float] = []
        ttft_runs: list[float] = []
        translation_text = ""
        try:
            for _ in range(N_RUNS):
                t_e2e, _ = await measure_e2e(translator, fix)
                t_ttft, _, text = await measure_ttft(translator, fix)
                e2e_runs.append(t_e2e)
                ttft_runs.append(t_ttft)
                translation_text = text
        except Exception as e:
            print(f"  [{fix['label']}] 失败: {e}")
            # 空流（filler 应返回空）算 0ms 不是失败
            if "No generation chunks" in str(e):
                row = {
                    "config": label, "provider": provider, "model": model,
                    "label": fix["label"], "input": fix["text"], "context": fix["context"],
                    "translation": "", "e2e_mean_ms": 0, "e2e_max_ms": 0,
                    "ttft_mean_ms": 0, "ttft_max_ms": 0, "note": "empty_stream",
                }
                rows.append(row)
                print(f"  [{fix['label']:<22}] (空流，符合 prompt 规则)")
            continue
        row = {
            "config": label,
            "provider": provider,
            "model": model,
            "label": fix["label"],
            "input": fix["text"],
            "context": fix["context"],
            "translation": translation_text,
            "e2e_mean_ms": statistics.mean(e2e_runs),
            "e2e_max_ms": max(e2e_runs),
            "ttft_mean_ms": statistics.mean(ttft_runs),
            "ttft_max_ms": max(ttft_runs),
        }
        rows.append(row)
        snippet = translation_text[:48].replace("\n", " ")
        print(
            f"  [{fix['label']:<22}] "
            f"e2e={row['e2e_mean_ms']:>6.0f}ms  ttft={row['ttft_mean_ms']:>6.0f}ms  → {snippet}"
        )
    return {"config": label, "rows": rows}


async def bench_with_whisper_concurrent(label: str, provider: str, model: str | None) -> dict:
    """与 Whisper 转写并发时的翻译延迟."""
    print(f"\n{'='*78}\n[{label}] +Whisper 并发延迟测试\n{'='*78}")

    audio_path = Path(__file__).parent.parent / "tests" / "test_audio.wav"
    if not audio_path.exists():
        print(f"  跳过：未找到 {audio_path}")
        return {}

    try:
        import mlx_whisper
    except ImportError:
        print("  mlx_whisper 未安装，跳过")
        return {}

    repo = "mlx-community/whisper-small-mlx-q4"

    print("  whisper warmup ...")
    _ = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=repo, word_timestamps=False)

    try:
        translator = make_translator(provider, model)
    except Exception as e:
        print(f"  构造失败: {e}")
        return {}
    if not translator.is_ready:
        return {}
    await measure_e2e(translator, FIXTURES[0])  # translator warmup

    stop = asyncio.Event()

    async def whisper_loop():
        loop = asyncio.get_event_loop()
        while not stop.is_set():
            await loop.run_in_executor(
                None,
                lambda: mlx_whisper.transcribe(
                    str(audio_path), path_or_hf_repo=repo, word_timestamps=False
                ),
            )

    whisper_task = asyncio.create_task(whisper_loop())
    await asyncio.sleep(1.0)  # 让 whisper 进入稳态

    rows = []
    try:
        for fix in FIXTURES[:3]:  # 节省时间只测 3 条
            t_ttft, t_total, text = await measure_ttft(translator, fix)
            row = {
                "config": label,
                "provider": provider,
                "model": model,
                "label": fix["label"] + "_concurrent",
                "input": fix["text"],
                "translation": text,
                "ttft_concurrent_ms": t_ttft,
                "e2e_concurrent_ms": t_total,
            }
            rows.append(row)
            print(
                f"  [{fix['label']:<22}] +whisper "
                f"ttft={t_ttft:>6.0f}ms  e2e={t_total:>6.0f}ms"
            )
    finally:
        stop.set()
        await whisper_task

    return {"config": label, "rows": rows}


def print_summary(per_config: dict, concurrent: dict) -> None:
    print(f"\n{'='*100}\n汇总：单调用延迟 (e2e ms / ttft ms)\n{'='*100}")
    config_labels = list(per_config.keys())
    rows_by_config: dict[str, dict] = {
        cfg: {r["label"]: r for r in per_config[cfg].get("rows", [])} for cfg in config_labels
    }
    fixture_labels = sorted({k for cfg in rows_by_config.values() for k in cfg})

    header = f"{'fixture':<22}" + "".join(f"{cfg:>26}" for cfg in config_labels)
    print(header)
    print("-" * len(header))
    for fix_label in fixture_labels:
        line = f"{fix_label:<22}"
        for cfg in config_labels:
            r = rows_by_config[cfg].get(fix_label, {})
            e2e = r.get("e2e_mean_ms", 0)
            ttft = r.get("ttft_mean_ms", 0)
            line += f"  e2e={e2e:>5.0f} ttft={ttft:>5.0f}"
        print(line)

    print(f"\n{'='*100}\n质量审阅 (each config 的实际翻译输出)\n{'='*100}")
    for fix_label in fixture_labels:
        # 找原始输入
        original = next((r["input"] for cfg in rows_by_config.values()
                        for r in [cfg.get(fix_label, {})] if r.get("input")), "?")
        print(f"\n[{fix_label}] 原文: {original!r}")
        for cfg in config_labels:
            r = rows_by_config[cfg].get(fix_label, {})
            t = r.get("translation", "(无)")
            note = f"  ({r['note']})" if r.get("note") else ""
            print(f"  {cfg:<28} → {t!r}{note}")

    if concurrent:
        print(f"\n{'='*100}\n汇总：+Whisper 并发 (TTFT ms)\n{'='*100}")
        c_rows: dict[str, dict] = {
            cfg: {r["label"]: r for r in concurrent[cfg].get("rows", [])}
            for cfg in concurrent
        }
        c_fixture_labels = sorted({k for cfg in c_rows.values() for k in cfg})
        header = f"{'fixture':<32}" + "".join(f"{cfg:>26}" for cfg in c_rows)
        print(header)
        print("-" * len(header))
        for fix_label in c_fixture_labels:
            line = f"{fix_label:<32}"
            for cfg in c_rows:
                r = c_rows[cfg].get(fix_label, {})
                line += f"{r.get('ttft_concurrent_ms', 0):>22.0f}ms "
            print(line)

        print(f"\n并发 vs 单跑 TTFT 比 (>1.0 表示被拖慢):")
        for fix_label in c_fixture_labels:
            base = fix_label.removesuffix("_concurrent")
            for cfg in c_rows:
                single = rows_by_config.get(cfg, {}).get(base, {}).get("ttft_mean_ms")
                conc = c_rows[cfg].get(fix_label, {}).get("ttft_concurrent_ms")
                if single and conc:
                    ratio = conc / single
                    print(f"  {cfg:<28} {base:<22} {ratio:.2f}x  ({single:.0f} → {conc:.0f}ms)")


async def main():
    OUTPUT_PATH.write_text("")  # truncate

    per_config: dict = {}
    concurrent: dict = {}

    for label, provider, model in CONFIGS:
        try:
            r = await bench_config(label, provider, model)
            if r:
                per_config[label] = r
                with OUTPUT_PATH.open("a") as f:
                    for row in r["rows"]:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"  {label} 失败: {e}")
            import traceback; traceback.print_exc()

    for label, provider, model in CONFIGS:
        try:
            r = await bench_with_whisper_concurrent(label, provider, model)
            if r:
                concurrent[label] = r
                with OUTPUT_PATH.open("a") as f:
                    for row in r["rows"]:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"  {label} 并发测试失败: {e}")
            import traceback; traceback.print_exc()

    print_summary(per_config, concurrent)
    print(f"\n详细输出 → {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
