from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict

from faster_whisper import WhisperModel

from .online_summary import OnlineSummaryError, summarize_online
from .templates import get_empty_summary, get_meeting_label, validate_meeting_type


StageProgressHook = Callable[[str, int], None]

_WHISPER_MODEL: WhisperModel | None = None

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
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WHISPER_DOWNLOAD_ROOT = str(PROJECT_ROOT / "models")

MANAGEMENT_DEPARTMENTS: Dict[str, list[str]] = {
    "主席团": ["主席团", "主席", "副主席"],
    "秘书处": ["秘书处", "秘书"],
    "财务": ["财务", "报销", "预算"],
    "ARC代表": ["arc", "ARC", "代表"],
    "宣传部": ["宣传部", "宣传", "海报", "推文", "公众号"],
    "活动部": ["活动部", "活动", "流程", "场地"],
    "外联部": ["外联部", "外联", "企业", "赞助", "合作"],
    "组织部": ["组织部", "组织", "签到", "人员安排"],
    "人力部": ["人力部", "招新", "面试", "报名"],
    "技术部": ["技术部", "技术", "系统", "网站", "小程序"],
}

DECISION_KEYWORDS = [
    "决定",
    "确认",
    "通过",
    "就按",
    "定为",
    "安排",
    "明确",
]
PENDING_KEYWORDS = [
    "待确认",
    "还没定",
    "未确定",
    "再讨论",
    "看情况",
    "等通知",
    "不确定",
]
TODO_KEYWORDS = [
    "负责",
    "完成",
    "跟进",
    "提交",
    "整理",
    "制作",
    "发送",
    "对接",
    "确认",
    "准备",
    "推进",
]
TIME_PATTERNS = [
    re.compile(r"\d{1,2}月\d{1,2}[日号]?"),
    re.compile(r"(本周[一二三四五六日天]?前|下周[一二三四五六日天]?前|本周末|下周末)"),
    re.compile(r"(今天|明天|后天|今晚|本周|下周)"),
]
OWNER_PATTERNS = [
    re.compile(r"(宣传部|活动部|外联部|组织部|人力部|技术部|秘书处|主席团|财务|ARC代表)"),
    re.compile(r"([一-龥]{2,4})(同学|老师|主席|部长|负责人|代表)"),
]


async def process_audio(
    audio_path: Path,
    meta: Dict[str, Any],
    on_stage: StageProgressHook,
) -> Dict[str, Any]:
    meeting_type = validate_meeting_type(str(meta.get("meeting_type") or ""))

    on_stage("transcribing", 10)
    transcript = await asyncio.to_thread(transcribe_audio, audio_path)
    on_stage("transcribing", 45)

    clean_text = normalize_transcript(transcript)

    on_stage("summarizing", 60)
    summary_mode = "offline"
    warning: str | None = None
    use_online = bool(meta.get("use_online_summary"))

    if use_online:
        try:
            structured_summary = await asyncio.to_thread(summarize_online, clean_text, meta)
            summary_mode = "online"
        except OnlineSummaryError as exc:
            warning = f"在线总结失败，已回退离线模式：{exc}"
            structured_summary = summarize_offline(clean_text, meeting_type)
            summary_mode = "offline_fallback"
    else:
        structured_summary = summarize_offline(clean_text, meeting_type)

    on_stage("rendering", 88)
    markdown = render_markdown(structured_summary, meta, summary_mode, warning)
    on_stage("rendering", 96)

    return {
        "transcript": transcript,
        "structured_summary": structured_summary,
        "summary_mode": summary_mode,
        "warning": warning,
        "markdown": markdown,
    }


def transcribe_audio(audio_path: Path) -> str:
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
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def normalize_transcript(transcript: str) -> str:
    clean = transcript.replace("\r\n", "\n").replace("\r", "\n")
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean


def summarize_offline(clean_text: str, meeting_type: str) -> Dict[str, Any]:
    validate_meeting_type(meeting_type)
    sentences = split_sentences(clean_text)
    if meeting_type == "management_weekly":
        return summarize_management_offline(sentences)
    return summarize_recruitment_offline(sentences)


def summarize_management_offline(sentences: list[str]) -> Dict[str, Any]:
    summary = get_empty_summary("management_weekly")
    overview_topics = collect_overview_topics(sentences)

    for department, keywords in MANAGEMENT_DEPARTMENTS.items():
        related = [s for s in sentences if contains_any(s, keywords)]
        if not related:
            continue
        update = {
            "department": department,
            "progress": take_unique(related, 2),
            "issues": take_unique([s for s in related if is_pending(s)], 2),
            "support_needed": take_unique([s for s in related if "需要" in s or "配合" in s], 2),
        }
        summary["department_updates"].append(update)

    summary["coordination_issues"] = take_unique(
        [s for s in sentences if ("配合" in s or "协同" in s or "协调" in s or "支持" in s)],
        5,
    )
    summary["weekly_decisions"] = take_unique([s for s in sentences if is_decision(s)], 6)
    summary["weekly_todos"] = build_todos([s for s in sentences if is_todo(s)], 8)
    summary["pending_items"] = take_unique([s for s in sentences if is_pending(s)], 6)
    summary["overview"] = build_overview(
        "本次管理层周例会主要围绕各部门本周推进情况、协同问题和本周任务安排展开。",
        overview_topics,
    )
    return summary


def summarize_recruitment_offline(sentences: list[str]) -> Dict[str, Any]:
    summary = get_empty_summary("recruitment_prep")
    summary["weekly_progress"] = take_unique(
        [s for s in sentences if contains_any(s, ["完成", "已完成", "推进", "落实", "准备好了"])],
        6,
    )
    summary["additional_info"] = take_unique(
        [s for s in sentences if contains_any(s, ["补充", "另外", "还有", "说明", "提醒"])],
        5,
    )
    summary["next_week_focus"] = take_unique(
        [s for s in sentences if contains_any(s, ["下周", "接下来", "下一步", "重点"])],
        5,
    )
    summary["key_decisions"] = take_unique([s for s in sentences if is_decision(s)], 6)
    summary["weekly_todos"] = build_todos([s for s in sentences if is_todo(s)], 8)
    summary["risks_or_pending"] = take_unique([s for s in sentences if is_pending(s)], 6)
    summary["overview"] = build_overview(
        "本次招聘会筹备会议主要回顾了本周进展，并整理了下周重点、关键决策和待办事项。",
        collect_overview_topics(sentences),
    )
    return summary


def render_markdown(
    structured_summary: Dict[str, Any],
    meta: Dict[str, Any],
    summary_mode: str,
    warning: str | None,
) -> str:
    meeting_type = validate_meeting_type(structured_summary["meeting_type"])
    meeting_date = meta.get("meeting_date") or "未明确"
    meeting_label = get_meeting_label(meeting_type)

    lines = [
        f"# {meeting_date} {meeting_label}纪要",
        "",
        "## 会议信息",
        f"- 会议类型：{meeting_label}",
        f"- 会议日期：{meeting_date}",
        f"- 生成模式：{summary_mode}",
    ]
    if warning:
        lines.append(f"- 备注：{warning}")
    lines.extend(
        [
            "",
            "## 会议概览",
            f"- {structured_summary.get('overview') or '本次会议已完成转写，但概览暂未提取成功。'}",
            "",
        ]
    )

    if meeting_type == "management_weekly":
        append_management_markdown(lines, structured_summary)
    else:
        append_recruitment_markdown(lines, structured_summary)

    return "\n".join(lines).strip() + "\n"


def append_management_markdown(lines: list[str], summary: Dict[str, Any]) -> None:
    lines.append("## 各部门/角色汇报")
    updates = summary.get("department_updates") or []
    if not updates:
        lines.append("- 暂未提取到明确的部门汇报。")
    for item in updates:
        lines.append(f"### {item['department']}")
        append_string_section(lines, item.get("progress"), "进展")
        append_string_section(lines, item.get("issues"), "问题")
        append_string_section(lines, item.get("support_needed"), "需要配合")
        lines.append("")

    lines.append("## 需要讨论和协调的问题")
    append_string_list(lines, summary.get("coordination_issues"), empty_text="暂未提取到明确的协同问题。")
    lines.append("")

    lines.append("## 本周关键决定")
    append_string_list(lines, summary.get("weekly_decisions"), empty_text="暂未提取到明确的关键决定。")
    lines.append("")

    lines.append("## 本周 Todo")
    append_todos(lines, summary.get("weekly_todos"))
    lines.append("")

    lines.append("## 待确认事项")
    append_string_list(lines, summary.get("pending_items"), empty_text="暂未提取到明确的待确认事项。")


def append_recruitment_markdown(lines: list[str], summary: Dict[str, Any]) -> None:
    lines.append("## 本周进展")
    append_string_list(lines, summary.get("weekly_progress"), empty_text="暂未提取到明确的本周进展。")
    lines.append("")

    lines.append("## 补充信息")
    append_string_list(lines, summary.get("additional_info"), empty_text="暂未提取到明确的补充信息。")
    lines.append("")

    lines.append("## 下周重点")
    append_string_list(lines, summary.get("next_week_focus"), empty_text="暂未提取到明确的下周重点。")
    lines.append("")

    lines.append("## 关键决策")
    append_string_list(lines, summary.get("key_decisions"), empty_text="暂未提取到明确的关键决策。")
    lines.append("")

    lines.append("## 本周 Todo")
    append_todos(lines, summary.get("weekly_todos"))
    lines.append("")

    lines.append("## 风险与待确认事项")
    append_string_list(lines, summary.get("risks_or_pending"), empty_text="暂未提取到明确的风险或待确认事项。")


def append_string_section(lines: list[str], items: list[str] | None, label: str) -> None:
    values = items or []
    if not values:
        lines.append(f"- {label}：未明确")
        return
    for item in values:
        lines.append(f"- {label}：{item}")


def append_string_list(lines: list[str], items: list[str] | None, empty_text: str) -> None:
    values = items or []
    if not values:
        lines.append(f"- {empty_text}")
        return
    for item in values:
        lines.append(f"- {item}")


def append_todos(lines: list[str], items: list[Dict[str, str]] | None) -> None:
    todos = items or []
    if not todos:
        lines.append("- 暂未提取到明确的 Todo。")
        return
    for item in todos:
        status_label = "已确认" if item.get("status") == "confirmed" else "待确认"
        lines.append(
            f"- [{status_label}] {item.get('task')}（负责人：{item.get('owner')}；时间：{item.get('deadline')}）"
        )


def split_sentences(text: str) -> list[str]:
    sentences = [clean_sentence(s) for s in re.split(r"[。！？!?;\n]+", text) if clean_sentence(s)]
    return sentences


def clean_sentence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^(然后|就是|那个|我们这边|这边|另外|还有|所以)\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def collect_overview_topics(sentences: list[str]) -> list[str]:
    topics: list[str] = []
    keyword_map = {
        "招新": ["招新", "报名", "面试"],
        "宣传": ["宣传", "海报", "推文"],
        "活动安排": ["活动", "流程", "场地"],
        "财务预算": ["财务", "预算", "报销"],
        "企业联络": ["企业", "外联", "合作", "赞助"],
    }
    for label, keywords in keyword_map.items():
        if any(contains_any(sentence, keywords) for sentence in sentences):
            topics.append(label)
    return topics[:4]


def build_overview(default_text: str, topics: list[str]) -> str:
    if not topics:
        return default_text
    return f"{default_text} 重点涉及：{'、'.join(topics)}。"


def build_todos(sentences: list[str], limit: int) -> list[Dict[str, str]]:
    todos: list[Dict[str, str]] = []
    seen: set[str] = set()
    for sentence in sentences:
        task = sentence[:100].strip()
        if not task or task in seen:
            continue
        seen.add(task)
        todos.append(
            {
                "task": task,
                "owner": extract_owner(sentence),
                "deadline": extract_deadline(sentence),
                "status": "pending" if is_pending(sentence) else "confirmed",
            }
        )
        if len(todos) >= limit:
            break
    return todos


def extract_owner(sentence: str) -> str:
    for pattern in OWNER_PATTERNS:
        match = pattern.search(sentence)
        if not match:
            continue
        if match.lastindex and match.lastindex >= 2:
            return match.group(1).strip()
        return match.group(0).strip()
    return "负责人未明确"


def extract_deadline(sentence: str) -> str:
    for pattern in TIME_PATTERNS:
        match = pattern.search(sentence)
        if match:
            return match.group(0).strip()
    return "时间未明确"


def contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def is_decision(sentence: str) -> bool:
    return contains_any(sentence, DECISION_KEYWORDS) and not is_pending(sentence)


def is_pending(sentence: str) -> bool:
    return contains_any(sentence, PENDING_KEYWORDS)


def is_todo(sentence: str) -> bool:
    return contains_any(sentence, TODO_KEYWORDS)


def take_unique(items: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


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
