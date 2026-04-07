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
        "数组元素必须使用简洁书面中文，不要保留明显口头禅。"
        "只有明确决定的内容才能进入决策，只有明确可执行事项才能进入 todo。"
        "如果信息不足，请返回空数组或空字符串，不要猜测。"
    )
    user_prompt = (
        f"会议类型：{meeting_type}\n"
        f"会议日期：{meta.get('meeting_date') or '未提供'}\n"
        "请严格按照下面的 JSON schema 返回结果：\n"
        f"{schema_json}\n\n"
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
