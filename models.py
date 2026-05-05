from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Course:
    id: int
    name: str
    code: str


@dataclass
class Assignment:
    id: int
    name: str
    category: str
    points_possible: float
    score: float | None
    submitted: bool
    due_at: datetime | None


@dataclass
class GradeResult:
    letter: str
    percentage: float
    by_category: dict[str, float]
    complete_pct: float
