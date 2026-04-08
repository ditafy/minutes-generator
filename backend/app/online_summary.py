from __future__ import annotations

import ast
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

DECISION_HINTS = [
    "决定",
    "确定",
    "确认",
    "明确",
    "敲定",
    "定为",
    "采用",
    "使用",
]
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
    "搭建",
    "创建",
    "走访",
    "调研",
    "收集",
    "记录",
    "拍摄",
    "联系了",
    "发起",
    "提交了",
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
    "安排",
    "跟进",
    "完善",
]
RISK_HINTS = [
    "风险",
    "问题",
    "卡住",
    "受阻",
    "来不及",
    "赶不上",
    "不足",
    "缺少",
    "缺乏",
    "不够",
    "不愿意参与",
    "参与意愿低",
    "响应较少",
    "回复较少",
    "尚未回复",
    "无人报名",
    "推进困难",
    "没回",
    "还没回",
    "一直没回",
    "都没回",
    "没消息",
    "还没消息",
    "没下文",
    "没有下文",
    "还没动静",
    "没反馈",
    "还没反馈",
    "没答复",
    "还没答复",
    "时间紧张",
    "时间较紧",
    "周期紧",
    "有点赶",
    "很赶",
    "太赶了",
    "怕来不及",
    "赶不上",
    "时间有点卡",
    "时间卡得很死",
    "时间压得很紧",
    "卡住了",
    "卡在这",
    "还卡着",
    "没落实",
    "还没落实",
    "没落实下来",
    "未落实",
    "没搞定",
    "还没搞定",
    "没弄好",
    "还没弄好",
    "不招留学生",
    "不面向国际生",
    "不适合国际生",
    "对国际生不友好",
    "岗位不太适合国际生",
    "国际生机会不多",
    "不太愿意来",
    "不太想参加",
    "不是很想参加",
    "不怎么想来",
    "意愿不高",
    "兴趣不高",
    "积极性不高",
    "反应冷淡",
    "响应不足",
    "场地还没敲定",
    "场地还没着落",
    "场地未确认",
    "场地尚未回复",
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
    "还没定",
    "没定下来",
    "定不下来",
    "不确定",
    "不太确定",
    "说不好",
    "不好说",
    "悬着",
    "还悬着",
    "再决定",
    "后再决定",
    "还得看",
    "要再看",
    "先等等",
    "先放着",
]
TODO_HINTS = [
    "完成",
    "整理",
    "发送",
    "准备",
    "制作",
    "设计",
    "跟进",
    "联系",
    "确认",
    "完善",
    "提交",
    "推进",
]
BACKGROUND_HINTS = [
    "目标",
    "对象",
    "面向",
    "域名",
    "邮箱",
    "频率",
    "颜色",
    "方案",
    "渠道",
    "背景",
    "补充",
    "说明",
    "提醒",
]
PROGRESS_DETAIL_HINTS = [
    "时间线",
    "分工",
    "岗位",
    "联系",
    "企业",
    "公司",
    "域名",
    "邮箱",
    "视觉",
    "logo",
    "Logo",
    "方案",
    "网站",
    "社交媒体",
    "账号",
    "调研",
    "名单",
]
FILLER_PATTERNS = [
    re.compile(r"^(然后|就是|那个|我们这边|这边|另外|还有|所以|反正|其实|大概|感觉|我觉得)\s*"),
    re.compile(r"(嗯+|呃+|啊+|哦+|这个|那个)"),
    re.compile(r"(到时候|的话|这种|就是这样|就是说)"),
]
ADDITIONAL_GROUPS: list[tuple[str, list[str]]] = [
    ("对外沟通与参与范围", ["目标", "对象", "面向", "公司", "企业", "参与", "名单", "邀请"]),
    ("品牌与宣传细节", ["logo", "Logo", "颜色", "方案", "视觉", "宣传", "海报", "推广", "社交媒体"]),
    ("基础配置与执行信息", ["域名", "邮箱", "网站", "notion", "文档", "表格", "渠道"]),
    ("协作与会议机制", ["会议", "频率", "时间", "同步", "沟通", "安排", "分工", "职责"]),
    ("活动安排与场地背景", ["场地", "日期", "时间线", "流程", "活动"]),
]
OWNER_PATTERNS = [
    re.compile(r"(宣传部|活动部|外联部|组织部|人力部|技术部|秘书处|主席团|财务|ARC代表)"),
    re.compile(r"由\s*([A-Za-z][A-Za-z .-]{1,30})\s*负责"),
    re.compile(r"([A-Za-z][A-Za-z .-]{1,30})\s*负责"),
    re.compile(r"由\s*([一-龥A-Za-z]{2,20})(同学|老师|主席|部长|负责人|代表)\s*负责"),
    re.compile(r"([一-龥A-Za-z]{2,20})(同学|老师|主席|部长|负责人|代表)"),
]
TIME_PATTERNS = [
    re.compile(r"((?:(?:本周|下周)?周|(?:本周|下周))[一二三四五六日天]\s*\d{1,2}\s*点(?:\s*-\s*\d{1,2}\s*点半?)?)"),
    re.compile(r"((?:(?:本周|下周)?周|(?:本周|下周))[一二三四五六日天]\s*\d{1,2}\s*点半)"),
    re.compile(r"((?:(?:本周|下周)?周|(?:本周|下周))[一二三四五六日天](?:前|上午|下午|晚上)?)"),
    re.compile(r"\d{1,2}月\d{1,2}[日号]?"),
    re.compile(r"\d{1,2}月"),
    re.compile(r"(本周[一二三四五六日天]?前|下周[一二三四五六日天]?前|本周末|下周末)"),
    re.compile(r"(今天|明天|后天|今晚|本周|下周|10月\d{1,2}日)"),
]
RISK_PATTERNS = [
    re.compile(r"(至少|需要|还要)\s*\d+\s*(周|个月|月|天)"),
    re.compile(r"(至少|需要|还要)\s*[一二两三四五六七八九十]+\s*(周|个月|月|天)"),
    re.compile(r"(收到|等)\s*.*(proposal|邮件|材料|回复|消息).*(再决定|后再决定)"),
    re.compile(r"(尚未|还没|未)\s*(回复|确认|落实|搞定|敲定|定下来)"),
    re.compile(r"(没|没有)\s*(回|回复|消息|下文|反馈|答复|动静)"),
    re.compile(r"(不招|不面向|不适合).*(国际生|留学生)"),
]
RISK_CONTEXT_HINTS = [
    "企业",
    "公司",
    "会员单位",
    "场地",
    "政府",
    "机构",
    "proposal",
    "timeline",
    "时间线",
    "logo",
    "域名",
    "邮箱",
    "网站",
    "赞助",
    "国际生",
    "留学生",
    "宣传",
    "报名",
]


def summarize_online(transcript: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    meeting_type = validate_meeting_type(str(meta.get("meeting_type") or ""))
    system_prompt, user_prompt = _build_prompts(transcript, meta, meeting_type)
    content = _run_summary_model(system_prompt, user_prompt)

    parsed = _parse_json_response(content, meeting_type)
    draft = _normalize_summary(parsed, meeting_type)
    try:
        polished = _polish_summary_with_model(draft, transcript, meta, meeting_type)
        return polished
    except OnlineSummaryError:
        return draft


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
            "1. weekly_progress 必须覆盖目前为止已经做过的所有事情，记录已经推进、已经确认、已经准备或已有阶段性结果的事项；"
            "像走访同类活动、整理企业清单、企业邀请进展、政府和各类组织联系进展、确定品牌方向、搭建网站或邮箱等都应优先放这里。表达要使用正式纪要风格的总结，而不是直接搬运转写原句。\n"
            "2. additional_info 只放背景说明、补充备注、上下文信息，不能拿来承接本应属于 weekly_progress 的内容。\n"
            "3. next_week_focus 必须覆盖会议里提到的所有后续要做内容，可以和 weekly_todos 重复；每一条都要写清下周或后续要推进什么、推进目标是什么。\n"
            "4. weekly_progress 和 next_week_focus 都应分点列出，每个数组元素写成 1 到 2 句正式纪要总结性表达，不要写成短语、半句或直接摘抄转写。\n"
            "5. additional_info 的每一条应尽量包含：补充背景是什么、为什么需要说明、对筹备工作的影响是什么。表达要使用正式纪要风格的总结，而不是直接搬运转写原句。\n"
            "6. weekly_todos 只保留简洁 checklist 式任务，用短句描述可执行动作，不要写成长段说明；它应主要对应下周要做事项，可以和 next_week_focus 重合。\n"
            "7. key_decisions 必须提取所有已经明确拍板的事项，例如日期、方案、负责人、渠道、工具或执行方式的确认。表达要使用正式纪要风格的总结，而不是直接搬运转写原句。\n"
            "8. 如果有一些信息不属于进展、重点、决策、Todo、风险，但对理解会议很重要，应放入 additional_info，而不是留空。\n"
            "9. 最终输出必须是总结后的会议纪要文本，不能直接复制转写原句，不能保留口头禅、重复片段和聊天式表达。\n"
        )
    user_prompt = (
        f"会议类型：{meeting_type}\n"
        f"会议日期：{meta.get('meeting_date') or '未提供'}\n"
        "请严格按照下面的 JSON schema 返回结果：\n"
        f"{schema_json}\n"
        f"{section_rules}\n"
        "输出要求：缺失可留空，但不要把已出现的具体信息压缩得过短，也不要把不同栏目混放。"
        "其中 weekly_progress 与 next_week_focus 每个数组元素写成 1 到 2 句正式总结；weekly_todos 必须简洁。\n\n"
        "会议转写如下：\n"
        f"{transcript}"
    )
    return system_prompt, user_prompt


def _run_summary_model(system_prompt: str, user_prompt: str) -> str:
    if SUMMARY_PROVIDER == "openai":
        return _summarize_with_openai(system_prompt, user_prompt)
    if SUMMARY_PROVIDER == "ollama":
        return _summarize_with_ollama(system_prompt, user_prompt)
    raise OnlineSummaryError(f"unsupported summary provider: {SUMMARY_PROVIDER}")


def _parse_json_response(content: str, meeting_type: str) -> Dict[str, Any]:
    try:
        return _parse_json_content(content)
    except OnlineSummaryError:
        repaired = _repair_json_with_model(content, meeting_type)
        return _parse_json_content(repaired)


def _repair_json_with_model(content: str, meeting_type: str) -> str:
    schema_json = json.dumps(get_empty_summary(meeting_type), ensure_ascii=False, indent=2)
    system_prompt = (
        "你是 JSON 修复助手。"
        "请把给定内容整理成严格合法的 JSON，并严格符合给定 schema。"
        "只能输出 JSON，不允许输出解释、Markdown 或额外文字。"
        "如果原内容里有无关描述，只保留能映射到 schema 的内容。"
    )
    user_prompt = (
        "请把下面的内容修复为合法 JSON。schema 如下：\n"
        f"{schema_json}\n\n"
        "待修复内容如下：\n"
        f"{content}"
    )
    return _run_summary_model(system_prompt, user_prompt)


def _polish_summary_with_model(
    draft_summary: Dict[str, Any],
    transcript: str,
    meta: Dict[str, Any],
    meeting_type: str,
) -> Dict[str, Any]:
    schema_json = json.dumps(get_empty_summary(meeting_type), ensure_ascii=False, indent=2)
    draft_json = json.dumps(draft_summary, ensure_ascii=False, indent=2)
    system_prompt = (
        "你是学生社团会议纪要润色助手。"
        "请把给定的会议纪要草稿改写成正式、自然、非口语化的中文 JSON。"
        "最终输出必须严格符合 schema，只能输出 JSON。"
        "所有字符串字段、字符串数组元素、todo.task 都必须是总结后的纪要表达，"
        "不能直接照搬语音转写原句，不能保留聊天语气词、断裂句、口头禅或大段对话。"
        "如果 draft 中存在明显像原始转写的内容，请重写为正式总结。"
        "不要在正文里重复使用“本周已推进”“会议确认”“下周将重点推进”“当前仍需进一步确认”等固定前缀。"
        "栏目标题已经表达分类，正文应直接陈述事实、进展、安排和结论。"
        "owner、deadline、status 这类结构化信息应尽量保留。"
        "不要新增 schema 之外的字段，不要编造 transcript 中没有的信息。"
    )
    user_prompt = (
        f"会议类型：{meeting_type}\n"
        f"会议日期：{meta.get('meeting_date') or '未提供'}\n"
        "请按照下面的 schema 输出润色后的最终纪要 JSON：\n"
        f"{schema_json}\n\n"
        "下面是已经整理过的一版草稿，请在不丢失信息的前提下，"
        "把每个板块都重写成正式会议纪要表达。\n"
        "要求：weekly_progress 覆盖目前为止做过的所有事情，分点写成每点 1 到 2 句；"
        "next_week_focus 覆盖会议提到的所有后续事项，可与 weekly_todos 重合，分点写成每点 1 到 2 句；"
        "weekly_todos 写成简洁 checklist；最终内容必须是润色后的总结，不能直接摘抄转写。\n"
        "请不要使用固定模板前缀，而是直接写事项本身：\n"
        f"{draft_json}\n\n"
        "原始会议转写如下，可用于校验和补充上下文，但最终输出不能直接复制转写口语，要进行总结：\n"
        f"{transcript}"
    )
    polished_content = _run_summary_model(system_prompt, user_prompt)
    polished_data = _parse_json_response(polished_content, meeting_type)
    return _normalize_summary(polished_data, meeting_type)


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


def _normalize_summary(
    data: Dict[str, Any],
    meeting_type: str,
) -> Dict[str, Any]:
    normalized = get_empty_summary(meeting_type)

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
    _rewrite_recruitment_summary(normalized)
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
    result: list[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            raw_task = str(item.get("task") or item.get("content") or item.get("summary") or "").strip()
            owners = _normalize_owners(item.get("owners") or item.get("owner"))
            deadline = str(item.get("deadline") or "时间未明确").strip() or "时间未明确"
            status = str(item.get("status") or "confirmed").strip() or "confirmed"
        else:
            raw_task = _coerce_summary_text(item)
            owners = []
            deadline = "时间未明确"
            status = "pending" if _looks_like_pending(str(item or "")) else "confirmed"
        task = _rewrite_todo_task(_strip_todo_metadata(raw_task))
        if not task:
            continue
        if status not in {"confirmed", "pending"}:
            status = "confirmed"
        result.append(
            {
                "task": task,
                "owners": owners,
                "deadline": deadline,
                "status": status,
            }
        )
    return result


def _normalize_string_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _coerce_summary_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _coerce_summary_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean_extracted_text(_extract_structured_text_from_string(value))
    if isinstance(value, dict):
        return _clean_extracted_text(_flatten_structured_value(value))
    if isinstance(value, (list, tuple)):
        parts = [_coerce_summary_text(item) for item in value]
        merged = "；".join(part for part in parts if part)
        return _clean_extracted_text(merged)
    return _clean_extracted_text(str(value))


def _flatten_structured_value(value: Dict[str, Any]) -> str:
    if not value:
        return ""

    topic = _coerce_summary_text(value.get("topic"))
    result = _coerce_summary_text(value.get("result"))
    if topic and result:
        return f"{topic}：{result}"
    if topic:
        return topic
    if result:
        return result

    sentence = _compose_keyed_sentence(value, ["date", "time", "location", "owner", "deadline", "status"])
    if sentence:
        return sentence

    parts: list[str] = []
    for key in ["title", "summary", "content", "detail", "description", "note", "item", "value"]:
        text = _coerce_summary_text(value.get(key))
        if text:
            parts.append(text)

    if parts:
        return "；".join(_dedupe_preserve_order(parts))

    fallback_parts: list[str] = []
    for raw in value.values():
        text = _coerce_summary_text(raw)
        if text:
            fallback_parts.append(text)
    return "；".join(_dedupe_preserve_order(fallback_parts))


def _compose_keyed_sentence(value: Dict[str, Any], keys: list[str]) -> str:
    pieces: list[str] = []
    for key in keys:
        if key == "owner" and value.get("owners"):
            text = "、".join(_normalize_owners(value.get("owners")))
        else:
            text = _coerce_summary_text(value.get(key))
        if not text:
            continue
        label = {
            "date": "日期",
            "time": "时间",
            "location": "地点",
            "owner": "负责人",
            "deadline": "时间",
            "status": "状态",
        }.get(key, key)
        pieces.append(f"{label}为{text}")
    return "，".join(pieces)


def _extract_structured_text_from_string(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    parsed = _parse_pythonish_structure(raw)
    if isinstance(parsed, dict):
        return _flatten_structured_value(parsed)
    if isinstance(parsed, list):
        joined = "；".join(_coerce_summary_text(item) for item in parsed)
        if joined:
            return joined

    if "topic" in raw and "result" in raw:
        topic_match = re.search(r"['\"]topic['\"]\s*[:：]\s*['\"]([^'\"]+)['\"]", raw)
        result_match = re.search(r"['\"]result['\"]\s*[:：]\s*['\"]([^'\"]*)['\"]", raw)
        topic = _clean_extracted_text(topic_match.group(1) if topic_match else "")
        result = _clean_extracted_text(result_match.group(1) if result_match else "")
        if topic and result:
            return f"{topic}：{result}"
        if topic:
            return topic
        if result:
            return result

    keyed = _extract_key_value_pairs(raw)
    if keyed:
        return keyed
    return raw


def _parse_pythonish_structure(text: str) -> Any:
    candidate = str(text or "").strip()
    if not candidate or candidate[0] not in "{[":
        return None
    try:
        return ast.literal_eval(candidate)
    except (ValueError, SyntaxError):
        return None


def _extract_key_value_pairs(text: str) -> str:
    matches = re.findall(r"['\"]([^'\"]+)['\"]\s*[:：]\s*['\"]([^'\"]*)['\"]", text)
    if not matches:
        return ""

    pairs: list[str] = []
    for key, value in matches:
        cleaned_value = _clean_extracted_text(value)
        if not cleaned_value:
            continue
        if key in {"topic", "title"}:
            pairs.append(cleaned_value)
        elif key in {"result", "summary", "content", "detail", "description", "note"}:
            if pairs:
                pairs[-1] = f"{pairs[-1]}：{cleaned_value}"
            else:
                pairs.append(cleaned_value)
        elif key in {"date", "time", "location", "owner", "deadline", "status"}:
            label = {
                "date": "日期",
                "time": "时间",
                "location": "地点",
                "owner": "负责人",
                "deadline": "时间",
                "status": "状态",
            }[key]
            pairs.append(f"{label}为{cleaned_value}")
        else:
            pairs.append(cleaned_value)
    return "，".join(_dedupe_preserve_order(pairs))


def _clean_extracted_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    cleaned = re.sub(r"^\{+|\}+$", "", cleaned)
    cleaned = re.sub(r"^\[+|\]+$", "", cleaned)
    cleaned = re.sub(r"^\s*[-•]+\s*", "", cleaned)
    cleaned = cleaned.replace("、同时，", "；同时，")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*-\s*", "-", cleaned)
    cleaned = re.sub(r"[，,；;:：]\s*$", "", cleaned)
    cleaned = re.sub(r"^[，,；;:：]\s*", "", cleaned)
    cleaned = re.sub(r"。(?=[，,；;])", "", cleaned)
    return cleaned.strip()


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


def _rewrite_recruitment_summary(summary: Dict[str, Any]) -> None:
    summary["weekly_progress"] = _dedupe_preserve_order(
        [_rewrite_progress_item(item) for item in (summary.get("weekly_progress") or []) if str(item or "").strip()]
    )[:6]
    summary["additional_info"] = _dedupe_preserve_order(
        [_rewrite_additional_item(item) for item in (summary.get("additional_info") or []) if str(item or "").strip()]
    )[:5]
    summary["next_week_focus"] = _dedupe_preserve_order(
        [_rewrite_next_step_item(item) for item in (summary.get("next_week_focus") or []) if str(item or "").strip()]
    )[:5]
    summary["key_decisions"] = _dedupe_preserve_order(
        [_rewrite_decision_item(item) for item in (summary.get("key_decisions") or []) if str(item or "").strip()]
    )[:6]

    rewritten_todos: list[Dict[str, str]] = []
    for item in summary.get("weekly_todos") or []:
        task = _rewrite_todo_task(item.get("task") or "")
        if not task:
            continue
        rewritten_todos.append(
            {
                "task": task,
                "owners": _normalize_owners(item.get("owners") or item.get("owner")),
                "deadline": str(item.get("deadline") or "时间未明确").strip() or "时间未明确",
                "status": str(item.get("status") or "confirmed").strip() or "confirmed",
            }
        )
    summary["weekly_todos"] = _dedupe_todos(rewritten_todos)[:8]

    summary["risks_or_pending"] = _dedupe_preserve_order(
        [_rewrite_pending_item(item) for item in (summary.get("risks_or_pending") or []) if str(item or "").strip()]
    )[:6]


def _looks_like_progress(text: str) -> bool:
    cleaned = _clean_clause(text)
    if not cleaned:
        return False
    if _starts_with_any(cleaned, ["下周", "接下来", "下一步", "后续", "后面"]):
        return False
    return _contains_any(cleaned, PROGRESS_HINTS) or bool(re.search(r"(已|已经|完成了|搭建了|创建了|联系了|发了|整理了)", cleaned))


def _looks_like_decision(text: str) -> bool:
    cleaned = _clean_clause(text)
    if not cleaned:
        return False
    return _contains_any(cleaned, DECISION_HINTS) or bool(re.search(r"(负责人|颜色方案|时间为|目标群体|定为)", cleaned))


def _looks_like_next_step(text: str) -> bool:
    cleaned = _clean_clause(text)
    if not cleaned:
        return False
    if _starts_with_any(cleaned, ["下周", "接下来", "下一步", "后续", "后面"]):
        return True
    if _contains_any(cleaned, ["需要继续", "继续推进", "计划", "安排", "跟进", "完善", "尽快"]):
        return True
    return "推进" in cleaned and not _looks_like_progress(cleaned)


def _looks_like_pending(text: str) -> bool:
    cleaned = _clean_clause(text)
    if not cleaned:
        return False
    return _contains_any(cleaned, PENDING_HINTS) or bool(
        re.search(r"(收到|等)\s*.*(proposal|邮件|材料|回复|消息).*(再决定|后再决定)", cleaned)
    )


def _looks_like_risk_or_pending(text: str) -> bool:
    cleaned = _clean_clause(text)
    if not cleaned:
        return False
    if _contains_any(cleaned, RISK_HINTS):
        return True
    if any(pattern.search(cleaned) for pattern in RISK_PATTERNS):
        return True
    if _looks_like_pending(cleaned) and _contains_any(cleaned, RISK_CONTEXT_HINTS):
        return True
    return False


def _looks_like_background(text: str) -> bool:
    cleaned = _clean_clause(text)
    if not cleaned:
        return False
    return _contains_any(cleaned, BACKGROUND_HINTS)


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _starts_with_any(text: str, prefixes: list[str]) -> bool:
    return any(text.startswith(prefix) for prefix in prefixes)


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


def _dedupe_todos(items: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    result: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        task = str(item.get("task") or "").strip()
        if not task or task in seen:
            continue
        seen.add(task)
        result.append(
            {
                "task": task,
                "owners": _normalize_owners(item.get("owners") or item.get("owner")),
                "deadline": str(item.get("deadline") or "时间未明确").strip() or "时间未明确",
                "status": str(item.get("status") or "confirmed").strip() or "confirmed",
            }
        )
    return result


def _compress_clause(text: str) -> str:
    cleaned = _clean_clause(text)
    if not cleaned:
        return ""
    fragments = _pick_informative_fragments(cleaned, limit=2)
    if fragments:
        cleaned = "、".join(fragments)
    cleaned = re.sub(r"(我们|大家|然后|就是|那个|这边|的话|到时候)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ，,;；、。")
    return cleaned[:52].rstrip("、。")

def _pick_informative_fragments(text: str, limit: int) -> list[str]:
    pieces = re.split(r"[，,；;。]", text)
    result: list[str] = []
    for piece in pieces:
        cleaned = re.sub(r"\s+", " ", piece).strip(" ，,;；")
        cleaned = re.sub(r"^(同时|另外|并且|而且|然后|后续|并|但)\s*[，,]?\s*", "", cleaned)
        if not cleaned or len(cleaned) < 5:
            continue
        if cleaned in result:
            continue
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _compose_summary_sentences(prefix: str, fragments: list[str], closing: str) -> str:
    clean_fragments = [frag for frag in fragments if frag]
    if not clean_fragments:
        return ""
    first = clean_fragments[0]
    second = clean_fragments[1] if len(clean_fragments) > 1 else ""
    sentences = [f"{prefix}{first}。"]
    if second:
        sentences.append(f"同时，会议还推进了{second}。")
    sentences.append(closing)
    return "".join(sentences)


def _rewrite_progress_item(text: str) -> str:
    cleaned = _strip_template_prefixes(_clean_clause(text))
    fragments = _pick_informative_fragments(cleaned, limit=2)
    if not fragments:
        return ""
    first = fragments[0]
    second = fragments[1] if len(fragments) > 1 else ""
    sentences = [f"{first}。"]
    if second:
        sentences.append(f"同时，{second}。")
    return "".join(sentences)


def _rewrite_additional_item(text: str) -> str:
    cleaned = _strip_template_prefixes(_clean_clause(text))
    if re.search(r"(日期为|时间为|地点为|负责人为|状态为)", cleaned) and not re.search(r"[。！？!?]", cleaned):
        return _ensure_periods(cleaned)
    fragments = _pick_informative_fragments(cleaned, limit=2)
    if not fragments:
        return ""
    return (
        f"{fragments[0]}。"
        f"{f'同时，{fragments[1]}。' if len(fragments) > 1 else '相关信息主要用于补充当前筹备背景和执行条件。'}"
    )


def _rewrite_next_step_item(text: str) -> str:
    cleaned = _strip_template_prefixes(_clean_clause(text))
    fragments = _pick_informative_fragments(cleaned, limit=2)
    if not fragments:
        return ""
    first = fragments[0]
    second = fragments[1] if len(fragments) > 1 else ""
    sentences = [f"{first}。"]
    if second:
        follow_up = second if second.startswith("继续推进") else f"继续推进{second}"
        sentences.append(f"同时，{follow_up}。")
    return "".join(sentences)


def _rewrite_decision_item(text: str) -> str:
    cleaned = _strip_template_prefixes(_clean_clause(text))
    fragments = _pick_informative_fragments(cleaned, limit=2)
    if not fragments:
        return ""
    return "".join(_ensure_periods(fragment) for fragment in fragments)


def _rewrite_todo_task(text: str) -> str:
    clause = _strip_template_prefixes(_compress_clause(text))
    if not clause:
        return ""
    clause = re.sub(r"^(继续推进|推进|处理|落实|完成)", "", clause).strip(" ，,;；")
    return clause[:80]


def _rewrite_pending_item(text: str) -> str:
    cleaned = _strip_template_prefixes(_clean_clause(text))
    fragments = _pick_informative_fragments(cleaned, limit=2)
    if not fragments:
        return ""
    first = fragments[0]
    second = fragments[1] if len(fragments) > 1 else ""
    sentences = [f"{first}。"]
    if second:
        sentences.append(f"同时，还需明确{second}。")
    return "".join(sentences)


def _clean_clause(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    for pattern in FILLER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\b(YES|yes|ok|OK)\b", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ，,;；")
    return cleaned


def _strip_template_prefixes(text: str) -> str:
    cleaned = str(text or "")
    patterns = [
        r"^(本周已推进)+",
        r"^(会议确认)+",
        r"^(下周将重点推进)+",
        r"^(当前仍需进一步确认)+",
        r"^(下周需要继续推进)+",
        r"^(下周需要重点推进)+",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned).strip(" ，,;；。")
    return cleaned


def _ensure_periods(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = cleaned.replace("。。", "。")
    if cleaned and cleaned[-1] not in "。！？":
        cleaned += "。"
    return cleaned


def _normalize_owners(value: Any) -> list[str]:
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
    return _dedupe_preserve_order(owners)


def _strip_todo_metadata(text: str) -> str:
    cleaned = _clean_clause(text)
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
    return cleaned.strip(" ，,;；")
