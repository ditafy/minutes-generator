from __future__ import annotations

from typing import Any, Dict


MEETING_TYPES = {
    "management_weekly",
    "recruitment_prep",
}


def validate_meeting_type(meeting_type: str) -> str:
    if meeting_type not in MEETING_TYPES:
        raise ValueError(f"unsupported meeting_type: {meeting_type}")
    return meeting_type


def get_empty_summary(meeting_type: str) -> Dict[str, Any]:
    validate_meeting_type(meeting_type)
    if meeting_type == "management_weekly":
        return {
            "meeting_type": meeting_type,
            "overview": "",
            "department_updates": [],
            "coordination_issues": [],
            "weekly_decisions": [],
            "weekly_todos": [],
            "pending_items": [],
        }
    return {
        "meeting_type": meeting_type,
        "overview": "",
        "weekly_progress": [],
        "additional_info": [],
        "next_week_focus": [],
        "key_decisions": [],
        "weekly_todos": [],
        "risks_or_pending": [],
    }


def get_meeting_label(meeting_type: str) -> str:
    validate_meeting_type(meeting_type)
    if meeting_type == "management_weekly":
        return "管理层周例会"
    return "招聘会筹备会议"
