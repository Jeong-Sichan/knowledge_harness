"""D6 기록 사이의 관계와 D12 앞뒤 순서. 구조화된 칸만 보고 규칙으로 판정한다."""
from __future__ import annotations

from .conditions import ANY, clean
from .model import Claim

NONE = "none"
RECITATION = "recitation"
CORRECTION = "correction"
CONDITION_DIFFERS = "condition_differs"
NEEDS_COMPARISON = "needs_comparison"
SUPPORT = "support"
CONFLICT = "conflict"


def overlaps(a: Claim, b: Claim) -> bool:
    """같은 문서에서 인용 구간이 겹치면 재인용이다. 버전은 보지 않는다."""
    return any(x.doc == y.doc and x.start < y.end and y.start < x.end for x in a.evidence for y in b.evidence)


def relation(new: Claim, old: Claim) -> str:
    """같은 주제·종류의 두 주장을 D6 ② 표의 순서대로 판정한다."""
    if new.topic != old.topic or new.kind != old.kind:
        return NONE
    if overlaps(new, old) and clean(new.value) == clean(old.value):
        return RECITATION
    if new.corrects == old.id:
        return CORRECTION
    differs = unknown = False
    for key in new.conditions.keys() | old.conditions.keys():
        if key not in new.conditions or key not in old.conditions:
            unknown = True
        else:
            a, b = clean(new.conditions[key]), clean(old.conditions[key])
            differs = differs or (a != b and ANY not in (a, b))
    if differs:
        return CONDITION_DIFFERS
    if unknown:
        return NEEDS_COMPARISON
    return SUPPORT if clean(new.value) == clean(old.value) else CONFLICT


def narrows(new: Claim, old: Claim) -> bool:
    """옛 주장이 전체(`*`)인 키를 새 주장이 특정 값으로 좁혔는지 본다."""
    return any(clean(value) == ANY and clean(new.conditions.get(key, ANY)) != ANY
               for key, value in old.conditions.items())


def is_earlier(a: Claim, b: Claim) -> bool:
    """B가 올릴 때 A를 봤으면 A가 먼저다. 시계는 쓰지 않는다."""
    return a.id in b.seen


def is_concurrent(a: Claim, b: Claim) -> bool:
    return not is_earlier(a, b) and not is_earlier(b, a)


def recitation_groups(claims: list[Claim]) -> list[list[Claim]]:
    """인용 구간이 겹쳐 이어진 주장끼리 묶는다."""
    groups: list[list[Claim]] = []
    for claim in claims:
        linked = [group for group in groups if any(overlaps(claim, other) for other in group)]
        groups = [group for group in groups if not any(group is item for item in linked)]
        groups.append([*(other for group in linked for other in group), claim])
    return groups


def independent_count(claims: list[Claim]) -> int:
    """재인용으로 이어진 주장은 근거 하나로 센다."""
    return len(recitation_groups(claims))
