from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Tuple
from urllib import error, request

from .templates import get_empty_summary, validate_meeting_type


class OnlineSummaryError(RuntimeError):
    pass


SUMMARY_PROVIDER = os.environ.get("SUMMARY_PROVIDER", "ollama").strip().lower()
TIMEOUT_SECONDS = float(os.environ.get("ONLINE_SUMMARY_TIMEOUT", "180"))

OPENAI_API_URL = os.environ.get("ONLINE_SUMMARY_API_URL", "https://api.openai.com/v1/chat/completions")
OPENAI_API_KEY = os.environ.get("ONLINE_SUMMARY_API_KEY", "")
OPENAI_MODEL = os.environ.get("ONLINE_SUMMARY_MODEL", "gpt-4o-mini")

OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

PROGRESS_HINTS = [
    "完成",
    "已完成",
    "推进",
    "落实",
    "确定",
    "确认",
    "对齐",
    "敲定",
    "讨论了",
    "规划了",
    "明确了",
    "整理了",
    "准备了",
]
NEXT_STEP_HINTS = [
    "下周",
    "接下来",
    "下一步",
    "后续",
    "后面",
    "尽快",
    "需要继续",
    "计划",
    "将",
]
PENDING_HINTS = [
    "待确认",
    "未确认",
    "尚未",
    "还没",
    "需要确认",
    "需要等待",
    "等",
    "看情况",
]


def summarize_online(transcript: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    meeting_type = validate_meeting_type(str(meta.get("meeting_type") or ""))
    system_prompt, user_prompt = _build_prompts(transcript, meta, meeting_type)

    if SUMMARY_PROVIDER == "openai":
        content = _summarize_with_openai(system_prompt, user_prompt)
    elif SUMMARY_PROVIDER == "ollama":
        content = _summarize_with_ollama(system_prompt, user_prompt)
    else:
        raise OnlineSummaryError(f"unsupported summary provider: {SUMMARY_PROVIDER}")

    parsed = _parse_json_content(content)
    return _normalize_summary(parsed, meeting_type)


def _build_prompts(transcript: str, meta: Dict[str, Any], meeting_type: str) -> Tuple[str, str]:
    schema = get_empty_summary(meeting_type)
    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

    system_prompt = (
        "你是学生社团会议纪要助手。"
        "请根据会议转写内容输出严格合法的 JSON，对应给定 schema。"
        "只能输出 JSON，不允许输出解释、Markdown、前言或结尾。"
        "不要补充 schema 以外的字段。"
        "会议语言以中文为主，可能夹杂少量英文单词。"
        "数组元素必须使用简洁但信息充分的书面中文，不要保留明显口头禅。"
        "每条尽量写出动作、对象和当前状态，避免过度概括成几个字。"
        "如果转写里有多项具体工作，请优先保留更多有效细节，而不是只写笼统结论。"
        "只有明确决定的内容才能进入决策，只有明确可执行事项才能进入 todo。"
        "如果信息不足，请返回空数组或空字符串，不要猜测。"
    )
    section_rules = ""
    if meeting_type == "recruitment_prep":
        section_rules = (
            "\n招聘会筹备会议字段规则：\n"
            "1. overview 用 2 句左右概括会议讨论范围、当前推进状态和主要阻塞，不要只写一句空泛总结。\n"
            "2. weekly_progress 记录本周已经讨论清楚、已经推进、已经确认或已有阶段性结果的事项；"
            "像“讨论了目标和参与公司”“规划了时间线和分工”“明确了网站域名和邮箱细节”都应优先放这里。\n"
            "3. additional_info 只放背景说明、补充备注、上下文信息，不能拿来承接本应属于 weekly_progress 的内容。\n"
            "4. next_week_focus 只放后续要继续推进的重点事项。\n"
            "5. weekly_progress、additional_info、next_week_focus 这三个数组中的每一条都要写成 2 到 3 句话的完整总结，"
            "不要写成短语、半句或只有几个词的概括。\n"
            "6. weekly_progress 的每一条应尽量包含：讨论了什么、目前推进到什么程度、这项进展意味着什么。\n"
            "7. additional_info 的每一条应尽量包含：补充背景是什么、为什么需要说明、对筹备工作的影响是什么。\n"
            "8. next_week_focus 的每一条应尽量包含：接下来要做什么、为什么这是重点、预计要推进到什么结果。\n"
            "9. 若转写信息足够，weekly_progress 尽量提取 3 到 6 条具体内容；宁可少写几条，也不要把每条写得过短。\n"
        )
    user_prompt = (
        f"会议类型：{meeting_type}\n"
        f"会议日期：{meta.get('meeting_date') or '未提供'}\n"
        "请严格按照下面的 JSON schema 返回结果：\n"
        f"{schema_json}\n"
        f"{section_rules}\n"
        "输出要求：缺失可留空，但不要把已出现的具体信息压缩得过短，也不要把不同栏目混放。"
        "对于 weekly_progress、additional_info、next_week_focus，每个数组元素都应该是 2 到 3 句、信息完整的总结。\n\n"
        "会议转写如下：\n"
        f"{transcript}"
    )
    return system_prompt, user_prompt


def _summarize_with_openai(system_prompt: str, user_prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise OnlineSummaryError("openai summary is not configured")

    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    response_json = _post_json(
        url=OPENAI_API_URL,
        payload=payload,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    return _extract_openai_content(response_json)


def _summarize_with_ollama(system_prompt: str, user_prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.2,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    response_json = _post_json(
        url=OLLAMA_API_URL,
        payload=payload,
        headers={"Content-Type": "application/json"},
    )
    return _extract_ollama_content(response_json)


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise OnlineSummaryError(f"summary request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise OnlineSummaryError(f"summary request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OnlineSummaryError("summary request timed out") from exc


def _extract_openai_content(response_json: Dict[str, Any]) -> str:
    choices = response_json.get("choices") or []
    if not choices:
        raise OnlineSummaryError("openai summary returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text") or ""))
        if text_parts:
            return "".join(text_parts)
    raise OnlineSummaryError("openai summary returned empty content")


def _extract_ollama_content(response_json: Dict[str, Any]) -> str:
    message = response_json.get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    raise OnlineSummaryError("ollama summary returned empty content")


def _parse_json_content(content: str) -> Dict[str, Any]:
    text = content.strip()
    candidates = [text]

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        candidates.append(brace_match.group(0).strip())

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    raise OnlineSummaryError("summary returned invalid JSON")


def _normalize_summary(data: Dict[str, Any], meeting_type: str) -> Dict[str, Any]:
    normalized = get_empty_summary(meeting_type)
    normalized["overview"] = str(data.get("overview") or "").strip()

    if meeting_type == "management_weekly":
        normalized["department_updates"] = _normalize_department_updates(data.get("department_updates"))
        normalized["coordination_issues"] = _normalize_string_list(data.get("coordination_issues"))
        normalized["weekly_decisions"] = _normalize_string_list(data.get("weekly_decisions"))
        normalized["weekly_todos"] = _normalize_todos(data.get("weekly_todos"))
        normalized["pending_items"] = _normalize_string_list(data.get("pending_items"))
        return normalized

    normalized["weekly_progress"] = _normalize_string_list(data.get("weekly_progress"))
    normalized["additional_info"] = _normalize_string_list(data.get("additional_info"))
    normalized["next_week_focus"] = _normalize_string_list(data.get("next_week_focus"))
    normalized["key_decisions"] = _normalize_string_list(data.get("key_decisions"))
    normalized["weekly_todos"] = _normalize_todos(data.get("weekly_todos"))
    normalized["risks_or_pending"] = _normalize_string_list(data.get("risks_or_pending"))
    _rebalance_recruitment_sections(normalized)
    if not normalized["overview"]:
        normalized["overview"] = _build_recruitment_overview(normalized)
    return normalized


def _normalize_department_updates(value: Any) -> list[Dict[str, Any]]:
    items = value if isinstance(value, list) else []
    result: list[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        department = str(item.get("department") or "").strip()
        if not department:
            continue
        result.append(
            {
                "department": department,
                "progress": _normalize_string_list(item.get("progress")),
                "issues": _normalize_string_list(item.get("issues")),
                "support_needed": _normalize_string_list(item.get("support_needed")),
            }
        )
    return result


def _normalize_todos(value: Any) -> list[Dict[str, str]]:
    items = value if isinstance(value, list) else []
    result: list[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        task = str(item.get("task") or "").strip()
        if not task:
            continue
        status = str(item.get("status") or "confirmed").strip() or "confirmed"
        if status not in {"confirmed", "pending"}:
            status = "confirmed"
        result.append(
            {
                "task": task,
                "owner": str(item.get("owner") or "负责人未明确").strip() or "负责人未明确",
                "deadline": str(item.get("deadline") or "时间未明确").strip() or "时间未明确",
                "status": status,
            }
        )
    return result


def _normalize_string_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _rebalance_recruitment_sections(summary: Dict[str, Any]) -> None:
    progress = list(summary.get("weekly_progress") or [])
    additional = list(summary.get("additional_info") or [])
    next_week = list(summary.get("next_week_focus") or [])

    moved_to_progress: list[str] = []
    kept_additional: list[str] = []
    for item in additional:
        if _looks_like_progress(item) and not _looks_like_pending(item):
            moved_to_progress.append(item)
        elif _looks_like_next_step(item):
            next_week.append(item)
        else:
            kept_additional.append(item)

    stayed_progress: list[str] = []
    for item in progress:
        if _looks_like_next_step(item) and not _looks_like_progress(item):
            next_week.append(item)
        else:
            stayed_progress.append(item)

    summary["weekly_progress"] = _dedupe_preserve_order(stayed_progress + moved_to_progress)
    summary["additional_info"] = _dedupe_preserve_order(kept_additional)
    summary["next_week_focus"] = _dedupe_preserve_order(next_week)


def _build_recruitment_overview(summary: Dict[str, Any]) -> str:
    progress = summary.get("weekly_progress") or []
    next_week = summary.get("next_week_focus") or []
    pending = summary.get("risks_or_pending") or []

    parts: list[str] = []
    if progress:
        parts.append(f"本次招聘会筹备会议已推进{_join_preview(progress, 3)}等事项。")
    if next_week:
        parts.append(f"后续将重点跟进{_join_preview(next_week, 2)}。")
    if pending:
        parts.append(f"当前仍需关注{_join_preview(pending, 2)}。")
    return "".join(parts)


def _join_preview(items: list[str], limit: int) -> str:
    picked = [item for item in items[:limit] if item]
    if not picked:
        return ""
    return "、".join(picked)


def _looks_like_progress(text: str) -> bool:
    return _contains_any(text, PROGRESS_HINTS) and not _looks_like_next_step(text)


def _looks_like_next_step(text: str) -> bool:
    return _contains_any(text, NEXT_STEP_HINTS)


def _looks_like_pending(text: str) -> bool:
    return _contains_any(text, PENDING_HINTS)


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
