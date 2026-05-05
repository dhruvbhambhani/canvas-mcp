from __future__ import annotations
from models import Assignment, GradeResult


def apply_drop_lowest(pairs: list[tuple[float, float]], n: int) -> list[tuple[float, float]]:
    """Drop n assignments with the lowest score/points_possible ratio."""
    if n <= 0 or len(pairs) <= n:
        return pairs
    return sorted(pairs, key=lambda x: x[0] / max(x[1], 1e-9))[n:]


def _group_graded(assignments: list[Assignment]) -> dict[str, list[tuple[float, float]]]:
    groups: dict[str, list[tuple[float, float]]] = {}
    for a in assignments:
        if a.score is not None:
            groups.setdefault(a.category, []).append((a.score, a.points_possible))
    return groups


def _letter_from_pct(percentage: float, scale: dict[str, float]) -> str:
    for letter, threshold in sorted(scale.items(), key=lambda x: x[1], reverse=True):
        if percentage >= threshold:
            return letter
    return "F"


def compute_real_grade(assignments: list[Assignment], syllabus: dict) -> GradeResult:
    categories = syllabus.get("categories", [])
    scale = syllabus.get("scale", {"A": 90.0, "B": 80.0, "C": 70.0, "D": 60.0})
    scale = {k: float(v) for k, v in scale.items() if v is not None}

    graded = _group_graded(assignments)

    total_weight_used = 0.0
    total_weighted_score = 0.0
    by_category: dict[str, float] = {}

    total_weight = sum(float(cat.get("weight", 0) or 0) for cat in categories)

    for cat in categories:
        name = cat["name"]
        weight = float(cat.get("weight", 0) or 0)
        drop_n = int(cat.get("drop_lowest", 0) or 0)

        pairs = graded.get(name, [])
        if not pairs:
            continue

        pairs = apply_drop_lowest(pairs, drop_n)
        total_pts = sum(p for _, p in pairs)
        if total_pts == 0:
            continue

        cat_pct = sum(s for s, _ in pairs) / total_pts * 100
        by_category[name] = round(cat_pct, 2)
        total_weighted_score += cat_pct * weight / 100
        total_weight_used += weight

    if total_weight_used == 0:
        percentage = 0.0
    else:
        percentage = round(total_weighted_score / total_weight_used * 100, 2)

    complete_pct = round(total_weight_used / total_weight * 100, 1) if total_weight > 0 else 0.0

    return GradeResult(
        letter=_letter_from_pct(percentage, scale),
        percentage=percentage,
        by_category=by_category,
        complete_pct=complete_pct,
    )


def what_do_i_need(
    assignments: list[Assignment],
    target_letter: str,
    syllabus: dict,
) -> dict:
    categories = syllabus.get("categories", [])
    scale = syllabus.get("scale", {"A": 90.0, "B": 80.0, "C": 70.0, "D": 60.0})
    scale = {k: float(v) for k, v in scale.items() if v is not None}

    target_pct = scale.get(target_letter.upper(), 90.0)
    graded = _group_graded(assignments)

    # Categories with at least one ungraded assignment
    ungraded_cats: set[str] = {a.category for a in assignments if a.score is None}

    current_earned = 0.0
    remaining_weight = 0.0

    for cat in categories:
        name = cat["name"]
        weight = float(cat.get("weight", 0) or 0)
        drop_n = int(cat.get("drop_lowest", 0) or 0)

        pairs = graded.get(name, [])
        if pairs:
            pairs = apply_drop_lowest(pairs, drop_n)
            total_pts = sum(p for _, p in pairs)
            if total_pts > 0:
                cat_pct = sum(s for s, _ in pairs) / total_pts * 100
                current_earned += cat_pct * weight / 100

        if name in ungraded_cats:
            remaining_weight += weight

    if remaining_weight > 0:
        needed = (target_pct - current_earned) / remaining_weight * 100
        feasible = needed <= 100.0
    else:
        needed = 0.0
        feasible = current_earned >= target_pct

    return {
        "needed": round(needed, 1),
        "target": target_letter.upper(),
        "target_pct": target_pct,
        "current_earned": round(current_earned, 2),
        "remaining_weight": round(remaining_weight, 1),
        "feasible": feasible,
        "already_guaranteed": needed <= 0,
    }


if __name__ == "__main__":
    # Validation test: ESET 349 example from the project plan
    test_syllabus = {
        "categories": [
            {"name": "Attendance", "weight": 7, "drop_lowest": 0},
            {"name": "Exam 1", "weight": 20, "drop_lowest": 0},
            {"name": "Final", "weight": 25, "drop_lowest": 0},
            {"name": "Homework", "weight": 8, "drop_lowest": 1},
            {"name": "Lab", "weight": 20, "drop_lowest": 0},
            {"name": "Project", "weight": 10, "drop_lowest": 0},
            {"name": "Quizzes", "weight": 10, "drop_lowest": 1},
        ],
        "scale": {"A": 90, "B": 80, "C": 70, "D": 60},
        "mode": "weighted",
    }

    from datetime import datetime as dt
    test_assignments = [
        Assignment(1, "Attendance", "Attendance", 10, 10.0, True, None),
        Assignment(2, "Exam 1", "Exam 1", 100, 80.0, True, None),
        Assignment(3, "HW 1", "Homework", 10, 9.0, True, None),
        Assignment(4, "HW 2", "Homework", 10, 5.0, True, None),  # dropped
        Assignment(5, "Lab 1", "Lab", 20, 19.88, True, None),
        Assignment(6, "Lab 2", "Lab", 20, 20.0, True, None),
        Assignment(7, "Project", "Project", 100, 90.0, True, None),
        Assignment(8, "Quiz 1", "Quizzes", 10, 9.0, True, None),
        Assignment(9, "Quiz 2", "Quizzes", 10, 10.0, True, None),
        Assignment(10, "Quiz 3", "Quizzes", 10, 8.0, True, None),  # dropped
        # Final not yet graded
        Assignment(11, "Final Exam", "Final", 200, None, False, None),
    ]

    result = compute_real_grade(test_assignments, test_syllabus)
    print(f"Grade: {result.letter} ({result.percentage}%)")
    print(f"Semester completion: {result.complete_pct}%")
    for cat, pct in result.by_category.items():
        print(f"  {cat}: {pct:.1f}%")

    need = what_do_i_need(test_assignments, "A", test_syllabus)
    print(f"\nNeed {need['needed']}% on remaining work for an A")
    print(f"Feasible: {need['feasible']}")
