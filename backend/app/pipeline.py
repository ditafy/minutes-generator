from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Dict

import os

from faster_whisper import WhisperModel


StageProgressHook = Callable[[str, int], None]

_WHISPER_MODEL: WhisperModel | None = None

# 离线 STT：先用 medium（更稳）。如果你本地模型已下载，可把
# `local_files_only=True`，避免运行时联网下载。
WHISPER_MODEL_SIZE = "medium"
WHISPER_LANGUAGE = "zh"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_LOCAL_FILES_ONLY = os.environ.get("WHISPER_LOCAL_FILES_ONLY", "true").lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# 模型下载目录（可选）。使用项目内目录，方便你离线部署时打包。
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WHISPER_DOWNLOAD_ROOT = str(PROJECT_ROOT / "models")


async def process_audio_to_markdown(
    audio_path: Path,
    meta: Dict[str, Any],
    on_stage: StageProgressHook,
) -> str:
    """离线音频 -> 逐字稿 -> 保守主题/要点 -> Markdown。

    说明：
    - 当前版本重点完成“离线 STT 接入”。
    - `安排/共识`与`未决事项`仍保持保守策略：先输出待确认，避免误把讨论当决定。
    """

    def _load_model() -> WhisperModel:
        global _WHISPER_MODEL
        if _WHISPER_MODEL is not None:
            return _WHISPER_MODEL
        _WHISPER_MODEL = WhisperModel(
            model_size_or_path=WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
            download_root=WHISPER_DOWNLOAD_ROOT,
            local_files_only=WHISPER_LOCAL_FILES_ONLY,
        )
        return _WHISPER_MODEL

    def _transcribe() -> str:
        model = _load_model()
        segments, _info = model.transcribe(
            audio=str(audio_path),
            language=WHISPER_LANGUAGE,
            beam_size=1,
            vad_filter=True,
            without_timestamps=True,
            suppress_blank=True,
        )

        parts: list[str] = []
        # 转写段落串接成文本；不在这里做强清洗，后面再统一处理。
        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                parts.append(text)
        return "\n".join(parts)

    on_stage("stt", 10)
    transcript = await asyncio.to_thread(_transcribe)
    on_stage("stt", 55)

    # --- 清洗（轻量，避免丢信息） ---
    on_stage("clean", 65)
    clean = transcript.replace("\r\n", "\n").replace("\r", "\n")
    # 合并多余空白
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()

    # --- 保守“关键词主题归类”（MVP：不做决议/负责人推断） ---
    on_stage("extract", 80)
    themes_keywords: Dict[str, list[str]] = {
        "招新": ["招新", "报名", "招干", "面试", "筛选"],
        "活动": ["活动", "流程", "安排", "时间", "地点", "举办"],
        "宣传": ["宣传", "海报", "推文", "文案", "群里发", "宣传图", "公众号"],
        "经费": ["经费", "预算", "报销", "申请", "赞助", "审批"],
        "报名": ["报名", "表单", "二维码", "报名截止", "报名信息"],
        "物资": ["物资", "道具", "材料", "采购", "领取", "数量"],
        "群通知": ["群通知", "群发", "通知", "公告", "消息推送"],
    }

    # 用句号/问号/感叹号做粗分句；口语转写有时不规整，因此不过度依赖分句准确性。
    sentences = [s.strip() for s in re.split(r"[。！？!?\\n；;]+", clean) if s.strip()]
    if not sentences:
        sentences = [clean] if clean else []

    theme_to_snippets: Dict[str, list[str]] = {k: [] for k in themes_keywords.keys()}
    for s in sentences:
        matched: str | None = None
        for theme, kws in themes_keywords.items():
            if any(kw in s for kw in kws):
                matched = theme
                break
        if matched:
            # 每条句子最多收一类，避免一条内容污染多个主题
            if len(theme_to_snippets[matched]) < 8:
                theme_to_snippets[matched].append(s)

    # 选出出现最多的主题；如果全为空，就退回到“未明确”。
    scored = []
    for theme, snippets in theme_to_snippets.items():
        if snippets:
            scored.append((len(snippets), theme))
    scored.sort(reverse=True)

    top_themes = [theme for _, theme in scored[: min(7, max(1, len(scored)))]]
    if not top_themes:
        top_themes = ["未明确"]
        theme_to_snippets["未明确"] = [clean[:4000]] if clean else []

    # --- 渲染 Markdown ---
    on_stage("render", 92)

    meeting_title = meta.get("meeting_title") or "未明确"
    meeting_date = meta.get("meeting_date") or "未明确"
    club_name = meta.get("club_name") or "未明确"

    md_lines: list[str] = []
    md_lines.append(f"# {meeting_date} {meeting_title} 会议纪要（社团口语版）")
    md_lines.append("")
    md_lines.append("## 基本信息（录音里有啥就填啥）")
    md_lines.append("- 时间：未明确")
    md_lines.append("- 地点/线上：未明确")
    md_lines.append("- 主持：未明确")
    md_lines.append("- 记录：未明确")
    md_lines.append("")
    md_lines.append("## 今天聊了什么（议程/主题）")
    for t in top_themes:
        md_lines.append(f"- {t}")
    md_lines.append("")
    md_lines.append("## 讨论要点")

    for t in top_themes:
        md_lines.append(f"### {t}")
        snippets = theme_to_snippets.get(t, [])
        if not snippets:
            md_lines.append("- （未在转写中找到该主题的明确内容）")
        else:
            for s in snippets[:5]:
                # 保持口语版：尽量短句 bullet
                md_lines.append(f"- {s}")
        md_lines.append("")

    md_lines.append("## 最后怎么决定的（安排/共识）")
    md_lines.append(
        "- 【待确认】本版本先完成离线 STT 与要点归类；决议/安排抽取尚未接入（负责人：负责人未明确；时间：时间未明确）"
    )
    md_lines.append("")
    md_lines.append("## 还没定/需要再确认")
    md_lines.append(
        "- 【待确认】请接入后续的“决议/安排”抽取模块后再生成最终版安排（负责人：负责人未明确；时间：时间未明确）"
    )
    md_lines.append("")
    md_lines.append("## 还缺什么信息（从录音里没明确到）")
    md_lines.append("- 截止时间：时间未明确")
    md_lines.append("- 负责人：负责人未明确")
    md_lines.append(f"- 社团：{club_name}")

    return "\n".join(md_lines).strip() + "\n"

