from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict


StageProgressHook = Callable[[str, int], None]


async def process_audio_to_markdown(
    audio_path: Path,
    meta: Dict[str, Any],
    on_stage: StageProgressHook,
) -> str:
    """
    MVP 占位实现：先把“离线任务、进度、Markdown 模板”跑通。

    之后你会把这里替换成：
    1) 离线 STT 转写
    2) 文本清洗
    3) 结构化抽取（主题/要点/已定/待确认）
    4) 渲染 Markdown（含你的护栏规则）
    """

    # --- STT 阶段占位 ---
    on_stage("stt", 15)
    await asyncio.sleep(0.6)
    on_stage("stt", 45)
    await asyncio.sleep(0.6)

    # --- 清洗阶段占位 ---
    on_stage("clean", 60)
    await asyncio.sleep(0.4)

    # --- 抽取阶段占位 ---
    on_stage("extract", 80)
    await asyncio.sleep(0.5)

    # --- 渲染阶段占位 ---
    on_stage("render", 92)
    await asyncio.sleep(0.3)

    meeting_title = meta.get("meeting_title") or "未明确"
    meeting_date = meta.get("meeting_date") or "未明确"
    club_name = meta.get("club_name") or "未明确"

    md = f"""# {meeting_date} {meeting_title} 会议纪要（社团口语版）{chr(10)}

## 基本信息（录音里有啥就填啥）
- 时间：未明确
- 地点/线上：未明确
- 主持：未明确
- 记录：未明确

## 今天聊了什么（议程/主题）
- 未明确（MVP 尚未接入转写与主题抽取）

## 讨论要点
### 未明确
- （MVP 占位：请接入离线 STT + 结构化抽取后再生成真实要点）

## 最后怎么决定的（安排/共识）
- 【待确认】目前仅完成接口与模板跑通；离线 STT/抽取模块未接入（负责人：负责人未明确；时间：时间未明确）

## 还没定/需要再确认
- 【待确认】请在接入 STT/抽取后重新生成纪要（负责人：负责人未明确；时间：时间未明确）

## 还缺什么信息（从录音里没明确到）
- 截止时间：时间未明确
- 负责人：负责人未明确
- 社团：{club_name}
"""

    return md

