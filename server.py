"""
canvas-mcp server — runs the MCP stdio interface and WebSocket bridge together.

Start with: python server.py
Then open Canvas in Chrome with the extension installed.
"""
from __future__ import annotations
import asyncio
import os
from datetime import datetime, timezone, timedelta

from mcp.server.fastmcp import FastMCP

import cache
import canvas_client
import grade_calculator
import syllabus_parser
import ws_bridge

mcp = FastMCP("canvas-mcp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(v: float) -> str:
    return f"{v:.1f}%"


async def _course_name(course_id: int) -> str:
    for c in await canvas_client.get_courses():
        if c.id == course_id:
            return f"{c.code} — {c.name}"
    return str(course_id)


# ---------------------------------------------------------------------------
# Grade tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_real_grade(course_id: int) -> str:
    """Compute actual weighted grade for a course using syllabus weights."""
    assignments = await canvas_client.get_assignments(course_id)
    syllabus = await syllabus_parser.parse_syllabus(course_id)
    if not syllabus.get("categories"):
        return "No grade categories found in syllabus. Try get_syllabus to inspect it manually."

    result = grade_calculator.compute_real_grade(assignments, syllabus)
    name = await _course_name(course_id)

    lines = [
        f"Real grade for {name}",
        f"  Current:  {result.letter}  ({_pct(result.percentage)})",
        f"  Semester: {_pct(result.complete_pct)} complete",
        "",
        f"  {'Category':<22} {'Score':>8} {'Weight':>8} {'Contribution':>14}",
        "  " + "-" * 55,
    ]
    for cat in syllabus["categories"]:
        name_cat = cat["name"]
        weight = float(cat.get("weight", 0) or 0)
        if name_cat not in result.by_category:
            lines.append(f"  {name_cat:<22} {'—':>8} {_pct(weight):>8} {'(no data yet)':>14}")
        else:
            pct = result.by_category[name_cat]
            contrib = pct * weight / 100
            lines.append(f"  {name_cat:<22} {_pct(pct):>8} {_pct(weight):>8} {_pct(contrib):>14}")

    return "\n".join(lines)


@mcp.tool()
async def what_do_i_need(course_id: int, target_letter: str) -> str:
    """Calculate what score you need on remaining work to achieve a target letter grade."""
    assignments = await canvas_client.get_assignments(course_id)
    syllabus = await syllabus_parser.parse_syllabus(course_id)
    if not syllabus.get("categories"):
        return "No grade categories found in syllabus."

    r = grade_calculator.what_do_i_need(assignments, target_letter, syllabus)
    name = await _course_name(course_id)

    if r["already_guaranteed"]:
        return (
            f"You already have a {r['target']} guaranteed in {name}!\n"
            f"Current earned: {_pct(r['current_earned'])} (target: {_pct(r['target_pct'])})"
        )
    if not r["feasible"]:
        return (
            f"A {r['target']} is no longer mathematically possible in {name}.\n"
            f"You would need {_pct(r['needed'])} on the remaining "
            f"{_pct(r['remaining_weight'])} of your grade — exceeds 100%.\n"
            f"Current earned: {_pct(r['current_earned'])}"
        )
    return (
        f"To get a {r['target']} in {name}:\n"
        f"  You need:         {_pct(r['needed'])} average on remaining work\n"
        f"  Remaining weight: {_pct(r['remaining_weight'])} of your grade\n"
        f"  Current earned:   {_pct(r['current_earned'])} / {_pct(r['target_pct'])} target"
    )


@mcp.tool()
async def list_courses_with_grades() -> str:
    """Show all active courses with real weighted grades."""
    courses = await canvas_client.get_courses()
    if not courses:
        return "No active courses found. Make sure the extension is connected and you have Canvas open."

    lines = ["Active courses with real grades:", ""]
    for c in courses:
        assignments = await canvas_client.get_assignments(c.id)
        syllabus = await syllabus_parser.parse_syllabus(c.id)
        if syllabus.get("categories"):
            result = grade_calculator.compute_real_grade(assignments, syllabus)
            grade_str = f"{result.letter}  ({_pct(result.percentage)})  [{_pct(result.complete_pct)} done]"
        else:
            grade_str = "(syllabus weights not found — try get_syllabus)"
        lines.append(f"  [{c.id}]  {c.code:<12} {c.name}")
        lines.append(f"          {grade_str}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_grade_breakdown(course_id: int) -> str:
    """Show category-by-category grade breakdown with weights and contributions."""
    return await get_real_grade(course_id)


@mcp.tool()
async def get_syllabus_weights(course_id: int) -> str:
    """Show the parsed grade distribution from the course syllabus."""
    syllabus = await syllabus_parser.parse_syllabus(course_id)
    name = await _course_name(course_id)

    if not syllabus.get("categories"):
        return f"No grade categories found for {name}. The syllabus may not be structured in Canvas."

    lines = [f"Grade weights for {name}:", "", f"  Mode: {syllabus.get('mode', 'weighted')}"]

    scale = syllabus.get("scale", {})
    if scale:
        scale_str = "  ".join(f"{k}≥{int(v)}" for k, v in sorted(scale.items(), key=lambda x: -x[1]))
        lines.append(f"  Scale: {scale_str}")

    lines += ["", f"  {'Category':<22} {'Weight':>8} {'Drop Lowest':>12}", "  " + "-" * 44]

    for cat in syllabus["categories"]:
        drop = int(cat.get("drop_lowest", 0) or 0)
        lines.append(f"  {cat['name']:<22} {_pct(float(cat.get('weight', 0) or 0)):>8} {str(drop) if drop else '—':>12}")

    total = sum(float(c.get("weight", 0) or 0) for c in syllabus["categories"])
    lines += ["  " + "-" * 44, f"  {'Total':<22} {_pct(total):>8}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assignment tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_assignments(course_id: int) -> str:
    """List all assignments for a course with due dates and submission status."""
    assignments = await canvas_client.get_assignments(course_id)
    if not assignments:
        return f"No assignments found for course {course_id}."

    now = datetime.now(timezone.utc)
    name = await _course_name(course_id)
    lines = [f"Assignments for {name} ({len(assignments)} total):", ""]

    by_cat: dict[str, list] = {}
    for a in assignments:
        by_cat.setdefault(a.category, []).append(a)

    for cat, items in sorted(by_cat.items()):
        lines.append(f"  {cat}:")
        for a in sorted(items, key=lambda x: (x.due_at is None, x.due_at)):
            due = a.due_at.strftime("%b %d") if a.due_at else "no due date"
            if a.score is not None:
                status = f"✓ {a.score}/{a.points_possible}"
            elif a.submitted:
                status = "submitted"
            elif a.due_at and a.due_at < now:
                status = "MISSING"
            else:
                status = "pending"
            lines.append(f"    [{a.id}] {a.name:<42} {due:<10} {status}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_assignment_details(course_id: int, assignment_id: int) -> str:
    """Get full details of a single assignment including description and rubric."""
    details = await canvas_client.get_assignment_details(course_id, assignment_id)
    if "error" in details:
        return f"Error: {details['error']}"

    name = await _course_name(course_id)
    lines = [
        f"Assignment: {details['name']}",
        f"  Course:    {name}",
        f"  Points:    {details['points_possible']}",
        f"  Due:       {details['due_at'] or 'No due date'}",
        f"  Types:     {', '.join(details['submission_types']) or 'N/A'}",
        f"  Submitted: {'Yes' if details['submitted'] else 'No'}",
        f"  Score:     {details['score'] if details['score'] is not None else 'Not graded'}",
    ]
    if details["description"]:
        lines += ["", "Description:", details["description"][:2000]]
    if details["rubric"]:
        lines += ["", "Rubric:"]
        for c in details["rubric"]:
            lines.append(f"  • {c.get('description', '')} ({c.get('points', '')} pts)")

    return "\n".join(lines)


@mcp.tool()
async def list_upcoming_due_dates(days: int = 7) -> str:
    """List all due dates across every course in the next N days (default 7)."""
    courses = await canvas_client.get_courses()
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)

    upcoming = []
    for c in courses:
        for a in await canvas_client.get_assignments(c.id):
            if a.due_at and now <= a.due_at <= cutoff and a.score is None and not a.submitted:
                upcoming.append((a.due_at, c, a))

    if not upcoming:
        return f"Nothing due in the next {days} days."

    upcoming.sort(key=lambda x: x[0])
    lines = [f"Due in the next {days} days — {len(upcoming)} items:", ""]
    cur_date = None
    for due, course, a in upcoming:
        d = due.strftime("%A, %b %d")
        if d != cur_date:
            if cur_date:
                lines.append("")
            lines.append(f"  {d}:")
            cur_date = d
        lines.append(f"    {due.strftime('%I:%M %p')}  {course.code:<12} {a.name}  ({a.points_possible} pts)")

    return "\n".join(lines)


@mcp.tool()
async def get_grades(course_id: int) -> str:
    """Show raw scores for every assignment in a course."""
    assignments = await canvas_client.get_assignments(course_id)
    if not assignments:
        return f"No assignments found for course {course_id}."

    graded = [a for a in assignments if a.score is not None]
    name = await _course_name(course_id)
    lines = [
        f"Scores for {name}",
        f"  {len(graded)} graded / {len(assignments)} total",
        "",
        f"  {'Assignment':<42} {'Category':<16} {'Score':>7} {'Pts':>7} {'Pct':>7}",
        "  " + "-" * 82,
    ]
    for a in sorted(assignments, key=lambda x: x.category):
        if a.score is not None:
            pct = a.score / a.points_possible * 100 if a.points_possible else 0
            lines.append(f"  {a.name:<42} {a.category:<16} {a.score:>7.1f} {a.points_possible:>7.1f} {pct:>6.1f}%")
        else:
            status = "submitted" if a.submitted else "pending"
            lines.append(f"  {a.name:<42} {a.category:<16} {'—':>7} {a.points_possible:>7.1f} ({status})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Content tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_syllabus(course_id: int) -> str:
    """Get the full syllabus text for a course."""
    html = await canvas_client.get_syllabus_html(course_id)
    if not html:
        return f"No syllabus found for course {course_id}."
    text = syllabus_parser.strip_html(html)
    name = await _course_name(course_id)
    return f"Syllabus for {name}:\n\n{text[:8000]}"


@mcp.tool()
async def list_modules(course_id: int) -> str:
    """List course modules and their items."""
    modules = await canvas_client.get_modules(course_id)
    if not modules:
        return f"No modules found for course {course_id}."

    name = await _course_name(course_id)
    lines = [f"Modules for {name}:", ""]
    for mod in modules:
        lines.append(f"  {mod['name']}")
        for item in mod["items"]:
            suffix = f"  [page_url: {item['page_url']}]" if item.get("page_url") else ""
            lines.append(f"    • [{item['type']}] {item['title']}{suffix}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_page_content(course_id: int, page_url: str) -> str:
    """Get the text content of a Canvas page (lecture notes, readings, etc.)."""
    content = await canvas_client.get_page_content(course_id, page_url)
    if not content:
        return f"No content found for page '{page_url}'."
    name = await _course_name(course_id)
    return f"Page [{page_url}] in {name}:\n\n{content[:8000]}"


@mcp.tool()
async def list_announcements(course_id: int, count: int = 10) -> str:
    """List recent announcements from a course."""
    announcements = await canvas_client.get_announcements(course_id, count=count)
    if not announcements:
        return f"No announcements found for course {course_id}."

    name = await _course_name(course_id)
    lines = [f"Announcements for {name}:", ""]
    for ann in announcements:
        lines += [
            f"  {ann['posted_at'] or 'Unknown date'}  —  {ann['author']}",
            f"  {ann['title']}",
        ]
        if ann["message"]:
            preview = ann["message"][:300].replace("\n", " ")
            lines.append(f"  {preview}{'...' if len(ann['message']) > 300 else ''}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def generate_flashcards(course_id: int, page_url: str) -> str:
    """Generate Q&A flashcard pairs from a Canvas page. Requires ANTHROPIC_API_KEY in .env."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            "Flashcard generation requires an Anthropic API key.\n"
            "Add ANTHROPIC_API_KEY=sk-ant-... to your .env file.\n"
            "Get a free key at console.anthropic.com (free tier available)."
        )

    content = await canvas_client.get_page_content(course_id, page_url)
    if not content:
        return f"No content found for page '{page_url}'."

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": (
            "Generate 10-15 Q&A flashcard pairs from this content.\n"
            "Format each as:\nQ: [question]\nA: [answer]\n\n"
            f"Content:\n{content[:4000]}"
        )}],
    )
    name = await _course_name(course_id)
    return f"Flashcards for [{page_url}] in {name}:\n\n{response.content[0].text}"


# ---------------------------------------------------------------------------
# Status + cache tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def connection_status() -> str:
    """Check if the Chrome extension is connected."""
    if ws_bridge.is_connected():
        return (
            f"Connected\n"
            f"  Canvas: {ws_bridge.get_canvas_url()}\n"
            f"  User:   {ws_bridge.get_canvas_user()}"
        )
    return "Not connected. Open Canvas in Chrome with the canvas-mcp extension installed."


@mcp.tool()
async def refresh_cache() -> str:
    """Clear the local cache so the next request fetches fresh data from Canvas."""
    cache.clear_all()
    return "Cache cleared. Next requests will fetch fresh data from Canvas."


# ---------------------------------------------------------------------------
# Entry point — run WebSocket server + MCP together
# ---------------------------------------------------------------------------

async def _main():
    await ws_bridge.start()
    await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(_main())
