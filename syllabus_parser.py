"""
Regex-based syllabus parser. Extracts grade category weights, drop rules,
and grade scale from raw syllabus text — no LLM required.
"""
from __future__ import annotations
import re

import cache
import canvas_client

# Words that look like category names but aren't
_BLACKLIST = {
    "your", "the", "total", "final", "grade", "course", "class", "all", "any",
    "each", "this", "that", "will", "you", "are", "for", "and", "not", "may",
    "must", "late", "work", "policy", "below", "above", "week", "points",
}

_GRADE_LETTERS = ["A", "B", "C", "D", "F"]


def strip_html(html: str) -> str:
    import html as html_mod
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" :-–|*")
    return name


def _is_valid_name(name: str) -> bool:
    if len(name) < 3 or len(name) > 40:
        return False
    if name.lower() in _BLACKLIST:
        return False
    if any(skip in name.lower() for skip in ["http", "www", "@", "percent", "points"]):
        return False
    if re.match(r"^\d+$", name):
        return False
    return True


def _extract_categories(text: str) -> list[dict]:
    found: dict[str, float] = {}

    patterns = [
        # "Exams: 40%" or "Exams - 40%"
        r"([A-Z][A-Za-z &/\-]{2,35}?)\s*[:\-–]\s*(\d+(?:\.\d+)?)\s*%",
        # "40% Exams" or "40% - Exams"
        r"(\d+(?:\.\d+)?)\s*%\s*[:\-–]?\s*([A-Z][A-Za-z &/\-]{2,35}?)(?=\s*[\n,.(]|$)",
        # Table: | Exams | 40% |
        r"\|\s*([A-Z][A-Za-z &/\-]{2,30}?)\s*\|\s*(\d+(?:\.\d+)?)\s*%",
        # "Exams (40%)"
        r"([A-Z][A-Za-z &/\-]{2,35?})\s*\((\d+(?:\.\d+)?)\s*%\)",
        # "Exams ......... 40%"  (dot-leader table of contents style)
        r"([A-Z][A-Za-z &/\-]{2,35?})\s*\.{2,}\s*(\d+(?:\.\d+)?)\s*%",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.MULTILINE):
            g0, g1 = match.group(1).strip(), match.group(2).strip()
            # Determine which group is name vs weight
            if re.match(r"^\d", g0):
                weight_str, name = g0, g1
            else:
                name, weight_str = g0, g1

            try:
                weight = float(weight_str)
            except ValueError:
                continue

            name = _clean_name(name)
            if not _is_valid_name(name):
                continue
            if not (1 <= weight <= 100):
                continue
            if name not in found:
                found[name] = weight

    return [
        {"name": name, "weight": weight, "drop_lowest": 0, "points_possible": None}
        for name, weight in found.items()
    ]


def _extract_scale(text: str) -> dict[str, float]:
    scale: dict[str, float] = {}

    # "A: 90%", "A = 90", "A ≥ 90", "A- 90"
    for letter in _GRADE_LETTERS:
        pattern = rf"{letter}[+\-]?\s*[=:≥≥\-]\s*(\d+(?:\.\d+)?)"
        match = re.search(pattern, text)
        if match:
            scale[letter] = float(match.group(1))

    # "90-100 A" style
    if not scale:
        for letter in _GRADE_LETTERS:
            match = re.search(rf"(\d+)\s*[-–]\s*\d+\s+{letter}\b", text)
            if match:
                scale[letter] = float(match.group(1))

    return scale if len(scale) >= 2 else {}


def _apply_drop_rules(text: str, categories: list[dict]) -> None:
    """Mutates categories in-place with drop_lowest counts."""
    # "drop the lowest X quiz/homework scores"
    drop_pattern = re.compile(
        r"drop\s+(?:the\s+)?(?:lowest\s+)?(\d+|one|two|three)?\s*"
        r"(?:lowest\s+)?(?:score|grade|assignment)?s?\s+"
        r"(?:from\s+)?(?:your\s+)?([A-Za-z ]{2,30})",
        re.IGNORECASE,
    )
    word_to_n = {"one": 1, "two": 2, "three": 3}

    for match in drop_pattern.finditer(text):
        count_str = (match.group(1) or "1").lower()
        n = word_to_n.get(count_str, None)
        if n is None:
            try:
                n = int(count_str)
            except ValueError:
                n = 1
        category_hint = match.group(2).strip().lower()

        for cat in categories:
            if category_hint in cat["name"].lower() or cat["name"].lower() in category_hint:
                cat["drop_lowest"] = max(cat["drop_lowest"], n)

    # "lowest X dropped" / "lowest score dropped"
    simple = re.compile(
        r"([A-Za-z ]{2,30})[^.]*lowest\s+(?:\d+\s+)?(?:score|grade)s?\s+(?:will\s+be\s+)?dropped",
        re.IGNORECASE,
    )
    for match in simple.finditer(text):
        hint = match.group(1).strip().lower()
        for cat in categories:
            if hint in cat["name"].lower() or cat["name"].lower() in hint:
                if cat["drop_lowest"] == 0:
                    cat["drop_lowest"] = 1


async def parse_syllabus(course_id: int) -> dict:
    cache_key = f"syllabus:{course_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    html = await canvas_client.get_syllabus_html(course_id)
    if not html:
        return {"categories": [], "scale": {"A": 90, "B": 80, "C": 70, "D": 60}, "mode": "weighted"}

    text = strip_html(html)

    categories = _extract_categories(text)
    _apply_drop_rules(text, categories)
    scale = _extract_scale(text) or {"A": 90.0, "B": 80.0, "C": 70.0, "D": 60.0}

    total_weight = sum(c["weight"] for c in categories)
    mode = "weighted" if total_weight > 0 else "points"

    result = {"categories": categories, "scale": scale, "mode": mode}
    if categories:
        cache.set(cache_key, result, ttl_seconds=86400)
    return result
