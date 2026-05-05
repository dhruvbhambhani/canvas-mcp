"""
Canvas API client — fetches data through the Chrome extension WebSocket bridge.
All functions are async. No canvasapi library needed; auth is handled by the browser.
"""
from __future__ import annotations
import re
import sys
from datetime import datetime
from typing import Any

import cache
import ws_bridge
from models import Assignment, Course


def _strip_html(html: str) -> str:
    import html as html_mod
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


async def get_courses() -> list[Course]:
    cached = cache.get("courses")
    if cached is not None:
        return [Course(**c) for c in cached]

    data = await ws_bridge.request("/api/v1/courses", {
        "enrollment_state": "active",
        "include[]": "total_scores",
        "per_page": "100",
    })

    courses = []
    for c in (data or []):
        if not c.get("name"):
            continue
        courses.append(Course(
            id=c["id"],
            name=c["name"],
            code=c.get("course_code", "") or "",
        ))

    cache.set("courses", [vars(c) for c in courses], ttl_seconds=3600)
    return courses


async def get_assignments(course_id: int) -> list[Assignment]:
    groups_data = await ws_bridge.request(
        f"/api/v1/courses/{course_id}/assignment_groups",
        {"per_page": "100"},
    )
    groups: dict[int, str] = {g["id"]: g["name"] for g in (groups_data or [])}

    data = await ws_bridge.request(
        f"/api/v1/courses/{course_id}/assignments",
        {"include[]": "submission", "per_page": "100"},
    )

    assignments = []
    for a in (data or []):
        sub = a.get("submission") or {}
        raw_score = sub.get("score")
        score = float(raw_score) if raw_score is not None else None
        submitted = sub.get("workflow_state", "") in ("submitted", "graded")

        due_at: datetime | None = None
        if a.get("due_at"):
            try:
                due_at = datetime.fromisoformat(a["due_at"].replace("Z", "+00:00"))
            except ValueError:
                pass

        group_id = a.get("assignment_group_id")
        assignments.append(Assignment(
            id=a["id"],
            name=a["name"],
            category=groups.get(group_id, "Uncategorized"),
            points_possible=float(a.get("points_possible") or 0),
            score=score,
            submitted=submitted,
            due_at=due_at,
        ))

    return assignments


async def get_syllabus_html(course_id: int) -> str:
    data = await ws_bridge.request(
        f"/api/v1/courses/{course_id}",
        {"include[]": "syllabus_body"},
        single=True,
    )
    return (data or {}).get("syllabus_body") or ""


async def get_page_content(course_id: int, page_url: str) -> str:
    cache_key = f"page:{course_id}:{page_url}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = await ws_bridge.request(
        f"/api/v1/courses/{course_id}/pages/{page_url}",
        {},
        single=True,
    )
    body = (data or {}).get("body") or ""
    text = _strip_html(body)
    cache.set(cache_key, text, ttl_seconds=7200)
    return text


async def get_assignment_details(course_id: int, assignment_id: int) -> dict[str, Any]:
    data = await ws_bridge.request(
        f"/api/v1/courses/{course_id}/assignments/{assignment_id}",
        {"include[]": ["submission", "rubric"]},
        single=True,
    )
    if not data:
        return {"error": "Assignment not found"}

    sub = data.get("submission") or {}
    raw_score = sub.get("score")
    return {
        "id": data["id"],
        "name": data["name"],
        "description": _strip_html(data.get("description") or ""),
        "points_possible": float(data.get("points_possible") or 0),
        "due_at": data.get("due_at"),
        "submission_types": data.get("submission_types", []),
        "score": float(raw_score) if raw_score is not None else None,
        "submitted": sub.get("workflow_state", "") in ("submitted", "graded"),
        "rubric": data.get("rubric") or [],
    }


async def get_modules(course_id: int) -> list[dict[str, Any]]:
    data = await ws_bridge.request(
        f"/api/v1/courses/{course_id}/modules",
        {"include[]": "items", "per_page": "100"},
    )
    result = []
    for mod in (data or []):
        items = []
        for item in (mod.get("items") or []):
            items.append({
                "title": item.get("title", ""),
                "type": item.get("type", ""),
                "url": item.get("html_url", ""),
                "page_url": item.get("page_url"),
            })
        result.append({
            "name": mod.get("name", ""),
            "position": mod.get("position", 0),
            "items": items,
        })
    return result


async def get_announcements(course_id: int, count: int = 10) -> list[dict[str, Any]]:
    data = await ws_bridge.request(
        "/api/v1/announcements",
        {"context_codes[]": f"course_{course_id}", "per_page": str(count)},
    )
    result = []
    for ann in (data or [])[:count]:
        result.append({
            "title": ann.get("title", ""),
            "message": _strip_html(ann.get("message") or ""),
            "posted_at": ann.get("posted_at"),
            "author": (ann.get("author") or {}).get("display_name", "Unknown"),
        })
    return result
