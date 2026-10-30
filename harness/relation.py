"""관계 판정 모듈(Relation Judge): 새 기록이 들어오면 기존 기록과의 관계를 정한다.

| 관계              | 처리                                   |
|-------------------|----------------------------------------|
| none              | 새 공유 후보로 저장                    |
| condition_differs | 조건별 기록을 나란히 저장              |
| recitation        | 인용 관계로 연결, 새 근거로 세지 않음  |
| support           | 같은 조건·같은 주장, 다른 근거(독립 근거 +1) |
| conflict          | 양쪽 근거를 모두 유지하고 검토 요청    |

지금은 기록이 이미 구조화(topic/value/conditions)되어 있다고 보고 규칙으로 판정한다.
자유 텍스트 기록은 앞단 구조화 모듈(작은 모델, harness/llm.py)이 이 형태로 바꾼다.
"""
from __future__ import annotations

from .conditions import same_conditions
from .schema import Record

NONE = "none"
CONDITION_DIFFERS = "condition_differs"
RECITATION = "recitation"
SUPPORT = "support"
CONFLICT = "conflict"

# 대표 관계를 고를 때의 우선순위
_PRIORITY = [RECITATION, CONFLICT, SUPPORT, CONDITION_DIFFERS, NONE]


def judge_pair(new: Record, old: Record) -> str:
    if new.topic != old.topic:
        return NONE
    if {e.key for e in new.evidence} & {e.key for e in old.evidence}:
        return RECITATION
    if not same_conditions(new.conditions, old.conditions):
        return CONDITION_DIFFERS
    if new.value == old.value:
        return SUPPORT
    return CONFLICT


def judge(new: Record, existing: list[Record]) -> tuple[str, list[tuple[str, str]]]:
    """(대표 관계, [(상대 id, 관계), ...])를 돌려준다."""
    links = [(old.id, rel) for old in existing if (rel := judge_pair(new, old)) != NONE]
    if not links:
        return NONE, []
    rels = {rel for _, rel in links}
    primary = next(r for r in _PRIORITY if r in rels)
    return primary, links
