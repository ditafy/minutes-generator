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
    "未回复",
    "尚未回复",
    "没回",
    "还没回",
    "没消息",
    "没下文",
    "时间紧张",
    "有点赶",
    "来不及",
    "赶不上",
    "至少",
    "需要",
    "卡住了",
    "还没落实",
    "还没搞定",
    "不招国际生",
    "不招留学生",
    "参与意愿低",
    "不愿意参与",
    "意愿不高",
    "不太匹配",
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
    re.compile(r"((?:(?:本周|下周)?周|(?:本周|下周))[一二三四五六日天]\s*\d{1,2}\s*点(?:\s*-\s*\d{1,2}\s*点半?)?)"),
    re.compile(r"((?:(?:本周|下周)?周|(?:本周|下周))[一二三四五六日天]\s*\d{1,2}\s*点半)"),
    re.compile(r"((?:(?:本周|下周)?周|(?:本周|下周))[一二三四五六日天](?:前|上午|下午|晚上)?)"),
    re.compile(r"\d{1,2}月\d{1,2}[日号]?"),
    re.compile(r"(本周[一二三四五六日天]?前|下周[一二三四五六日天]?前|本周末|下周末)"),
    re.compile(r"(今天|明天|后天|今晚|本周|下周)"),
]
OWNER_PATTERNS = [
    re.compile(r"(宣传部|活动部|外联部|组织部|人力部|技术部|秘书处|主席团|财务|ARC代表)"),
    re.compile(r"由\s*([A-Za-z][A-Za-z .-]{1,30})\s*负责"),
    re.compile(r"([A-Za-z][A-Za-z .-]{1,30})\s*负责"),
    re.compile(r"由\s*([一-龥A-Za-z]{2,20})(同学|老师|主席|部长|负责人|代表)\s*负责"),
    re.compile(r"([一-龥A-Za-z]{2,20})(同学|老师|主席|部长|负责人|代表)"),
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
    lines.append("")

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
    append_mixed_string_list(
        lines,
        summary.get("additional_info"),
        empty_text="暂未提取到明确的补充信息。",
    )
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


def append_mixed_string_list(lines: list[str], items: list[str] | None, empty_text: str) -> None:
    values = items or []
    if not values:
        lines.append(f"- {empty_text}")
        return
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        if should_render_as_paragraph(text):
            lines.append(text)
            lines.append("")
        else:
            lines.append(f"- {text}")


def should_render_as_paragraph(text: str) -> bool:
    sentence_count = len([part for part in re.split(r"[。！？!?]", text) if part.strip()])
    return len(text) >= 90 or sentence_count >= 3


def append_todos(lines: list[str], items: list[Dict[str, Any]] | None) -> None:
    todos = items or []
    if not todos:
        lines.append("- 暂未提取到明确的 Todo。")
        return
    for item in todos:
        status_label = "已确认" if item.get("status") == "confirmed" else "待确认"
        owners = normalize_owners(item.get("owners") or item.get("owner"))
        owner_text = "、".join(owners) if owners else "负责人未明确"
        lines.append(
            f"- [{status_label}] {item.get('task')}（负责人：{owner_text}；时间：{item.get('deadline')}）"
        )


def split_sentences(text: str) -> list[str]:
    sentences = [clean_sentence(s) for s in re.split(r"[。！？!?;\n]+", text) if clean_sentence(s)]
    return sentences


def clean_sentence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^(然后|就是|那个|我们这边|这边|另外|还有|所以)\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def build_todos(sentences: list[str], limit: int) -> list[Dict[str, Any]]:
    todos: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for sentence in sentences:
        task = clean_todo_task(sentence)
        if not task or task in seen:
            continue
        seen.add(task)
        todos.append(
            {
                "task": task,
                "owners": extract_owners(sentence),
                "deadline": extract_deadline(sentence),
                "status": "pending" if is_pending(sentence) else "confirmed",
            }
        )
        if len(todos) >= limit:
            break
    return todos


def extract_owners(sentence: str) -> list[str]:
    cleaned = clean_sentence(sentence)
    owners: list[str] = []

    list_match = re.search(
        r"(?:由)?\s*([A-Za-z][A-Za-z .-]{1,20}|[一-龥]{2,6})\s*(?:和|与|跟|、|,|，)\s*([A-Za-z][A-Za-z .-]{1,20}|[一-龥]{2,6})(?:\s*一起)?\s*(负责|跟进|处理|完善|设计|联系|沟通|搭建|安排|发给|发送|提交|制作|准备)",
        cleaned,
    )
    if list_match:
        owners.extend([list_match.group(1).strip(), list_match.group(2).strip()])

    for pattern in OWNER_PATTERNS:
        for match in pattern.finditer(cleaned):
            owner = (match.group(1) if match.lastindex else match.group(0)).strip()
            if owner:
                owners.append(owner)

    verb_match = re.search(
        r"(?:由)?\s*([A-Za-z][A-Za-z .-]{1,20}|[一-龥]{2,6})\s*(?:负责|跟进|处理|完善|设计|联系|沟通|搭建)",
        cleaned,
    )
    if verb_match:
        owners.append(verb_match.group(1).strip())

    assigned_match = re.search(r"安排\s*([A-Za-z][A-Za-z .-]{1,20}|[一-龥]{2,6})\s*处理", cleaned)
    if assigned_match:
        owners.append(assigned_match.group(1).strip())

    return normalize_owners(owners)


def normalize_owners(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]

    owners: list[str] = []
    for raw in raw_items:
        text = str(raw or "").strip()
        if not text:
            continue
        text = re.sub(r"^负责人[:：]?\s*", "", text)
        text = re.sub(r"(同学|老师|主席|部长|负责人|代表)$", "", text).strip()
        parts = re.split(r"\s*(?:和|与|跟|、|,|，)\s*", text)
        for part in parts:
            cleaned = part.strip(" ，,;；。")
            if cleaned and cleaned not in {"负责人未明确", "未明确", "一起"}:
                owners.append(cleaned)

    deduped: list[str] = []
    seen: set[str] = set()
    for owner in owners:
        if owner not in seen:
            seen.add(owner)
            deduped.append(owner)
    return deduped


def clean_todo_task(sentence: str) -> str:
    cleaned = clean_sentence(sentence)
    cleaned = re.sub(
        r"^(?:由)?\s*(?:[A-Za-z][A-Za-z .-]{1,20}|[一-龥]{2,6})(?:\s*(?:和|与|跟|、|,|，)\s*(?:[A-Za-z][A-Za-z .-]{1,20}|[一-龥]{2,6}))*(?:\s*一起)?\s*(?=(负责|跟进|处理|完善|设计|联系|沟通|搭建))",
        "",
        cleaned,
    )
    cleaned = re.sub(r"^由\s*[A-Za-z][A-Za-z .-]{1,20}\s*负责\s*", "", cleaned)
    cleaned = re.sub(r"^由\s*[一-龥]{2,6}\s*负责\s*", "", cleaned)
    cleaned = re.sub(r"^(本周|下周)?周[一二三四五六日天](?:\s*\d{1,2}\s*点(?:\s*-\s*\d{1,2}\s*点半?)?)?\s*", "", cleaned)
    cleaned = re.sub(r"^(本周|下周|今天|明天|后天|今晚|本周末|下周末)\s*", "", cleaned)
    cleaned = re.sub(r"^(前|上午|下午|晚上)\s*", "", cleaned)
    return cleaned[:100].strip(" ，,;；")


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
    lowered = sentence.lower()
    if contains_any(sentence, PENDING_KEYWORDS):
        return True
    patterns = [
        r"(至少|需要|还要)\s*\d+\s*(周|个月|月|天)",
        r"(至少|需要|还要)\s*[一二两三四五六七八九十]+\s*(周|个月|月|天)",
        r"(收到|等)\s*.*(proposal|邮件|材料|回复|消息).*(再决定|后再决定)",
        r"(尚未|还没|未)\s*(回复|确认|落实|搞定|敲定|定下来)",
        r"(没|没有)\s*(回|回复|消息|下文|反馈|答复|动静)",
        r"(不招|不面向|不适合).*(国际生|留学生)",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


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
