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

    # --- 结构化抽取：安排/未决（保守，只从明确表态句抽已定） ---
    decision_keywords = [
        "决定",
        "确认",
        "我们就",
        "就这样",
        "就按",
        "从现在起",
        "同意",
        "通过",
        "安排",
        "要求",
        "需要",
        "请",
        "务必",
        "到",
        "截止",
        "最晚",
        "完成",
        "提交",
        "发给",
        "通知",
        "落实",
    ]

    # 条件/不确定语义：出现则更倾向放到“待确认/未决”
    conditional_keywords = [
        "可能",
        "考虑",
        "看看",
        "再看看",
        "再商量",
        "再讨论",
        "等",
        "等通知",
        "不确定",
        "看情况",
        "待定",
        "差不多",
        "大概",
        "应该",
        "或许",
        "到时候",
    ]

    open_keywords = [
        "还没定",
        "没定",
        "未确定",
        "待确认",
        "需要再确认",
        "还要再",
        "下一次再",
        "后面再",
        "之后再",
        "下次再",
        "需要补充",
    ]

    # 从句子里抽“负责人”：只在句子里出现类似 {名词}{同学/老师/负责人/...} 时才填
    name_suffixes = r"(同学|学长|学姐|老师|部长|负责人|主席|会长|队长|督导|指导老师)"
    name_patterns = [
        re.compile(rf"(?:由|请|麻烦)?([一-龥]{{2,4}}){name_suffixes}"),
        re.compile(rf"([一-龥]{{2,4}}){name_suffixes}"),
    ]

    # 抽取截止/时间：尽量匹配“xx月xx日/xx号/周x/明天/后天”等
    time_patterns = [
        re.compile(r"(截止|最晚|到)\s*(\d{1,2})\s*月\s*(\d{1,2})\s*(日|号)"),
        re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*(日|号)"),
        re.compile(r"(下?周[一二三四五六日天])"),
        re.compile(r"(明天|后天|今天)"),
        re.compile(r"(最晚)\s*(\d{1,2})\s*号"),
        re.compile(r"(到)\s*(\d{1,2})\s*号"),
        re.compile(r"(这周末)"),
    ]

    def _extract_owner(s: str) -> str:
        for pat in name_patterns:
            m = pat.search(s)
            if m:
                # group(1) should be the name
                name = m.group(1).strip()
                if name:
                    return name
        return "负责人未明确"

    def _extract_due(s: str) -> str:
        for pat in time_patterns:
            m = pat.search(s)
            if m:
                # 简单返回匹配到的整段
                return m.group(0).strip()
        return "时间未明确"

    def _clean_action_text(s: str) -> str:
        s = s.strip()
        # 去掉常见口语前缀，避免 action 文本太啰嗦
        s = re.sub(r"^(那我们|那就|接下来|下一步|好|行|所以|因此|我们就|我们先|我觉得|我看|大家|然后)\s*", "", s)
        s = re.sub(r"\s+", " ", s)
        if len(s) > 120:
            s = s[:120].rstrip() + "…"
        return s

    def _is_decision(s: str) -> bool:
        # 必须有“明确表态/安排/要求/完成类”关键词，且不能出现明显条件/不确定语义
        has_decision = any(kw in s for kw in decision_keywords)
        has_cond = any(kw in s for kw in conditional_keywords) or any(kw in s for kw in open_keywords)
        return has_decision and not has_cond

    def _is_open_issue(s: str) -> bool:
        # 非已定句里，只要出现明显“未决/待确认/不确定/再讨论”等，就认为是未决事项候选
        has_open = any(kw in s for kw in open_keywords)
        has_cond = any(kw in s for kw in conditional_keywords)
        return has_open or has_cond

    decisions: list[str] = []
    opens: list[str] = []
    seen_dec = set()
    seen_open = set()

    for s in sentences:
        if _is_decision(s):
            txt = _clean_action_text(s)
            if txt and txt not in seen_dec:
                decisions.append(txt)
                seen_dec.add(txt)
        elif _is_open_issue(s):
            txt = _clean_action_text(s)
            if txt and txt not in seen_open:
                opens.append(txt)
                seen_open.add(txt)

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
    if not decisions:
        md_lines.append("- （未在转写中找到明确的已定安排/共识）")
    else:
        for action in decisions[:12]:
            owner = _extract_owner(action)
            due = _extract_due(action)
            md_lines.append(f"- 【已定】{action}（负责人：{owner}；时间：{due}）")
    md_lines.append("")
    md_lines.append("## 还没定/需要再确认")
    if not opens:
        md_lines.append("- （未在转写中找到需要再确认的未决事项）")
    else:
        for action in opens[:12]:
            owner = _extract_owner(action)
            due = _extract_due(action)
            md_lines.append(f"- 【待确认】{action}（负责人：{owner}；时间：{due}）")
    md_lines.append("")
    md_lines.append("## 还缺什么信息（从录音里没明确到）")
    md_lines.append("- 截止时间：时间未明确")
    md_lines.append("- 负责人：负责人未明确")
    md_lines.append(f"- 社团：{club_name}")

    return "\n".join(md_lines).strip() + "\n"

