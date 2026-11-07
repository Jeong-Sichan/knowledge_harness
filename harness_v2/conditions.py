"""D5 조건 비교. 조건 키는 값, 전체(`*`), 미기재 중 하나다."""
from __future__ import annotations

from .model import Claim

ANY = "*"
MATCH = "match"
UNVERIFIED = "unverified"
MISMATCH = "mismatch"


def clean(value: str) -> str:
    """값 비교 전 정리. 대소문자와 공백 차이만 없앤다."""
    return " ".join(str(value).split()).casefold()


def relevant_keys(claims: list[Claim]) -> set[str]:
    """주제의 주장들에 한 번이라도 쓰인 키."""
    return {key for claim in claims for key in claim.conditions}


def differing_keys(question: dict[str, str], conditions: dict[str, str]) -> list[str]:
    return [key for key, wanted in question.items()
            if key in conditions and clean(conditions[key]) not in (ANY, clean(wanted))]


def compare(question: dict[str, str], conditions: dict[str, str], relevant: set[str]) -> str:
    """질문 조건과 주장 조건을 비교한다. 관련 없는 질문 키는 무시한다."""
    asked = {key: value for key, value in question.items() if key in relevant}
    if differing_keys(asked, conditions):
        return MISMATCH
    return UNVERIFIED if any(key not in conditions for key in asked) else MATCH


def nearest(question: dict[str, str], claims: list[Claim], limit: int = 3) -> list[Claim]:
    """조건이 다른 주장 중 다른 키가 적은 순서로 고른다."""
    return sorted(claims, key=lambda claim: (len(differing_keys(question, claim.conditions)), claim.id))[:limit]


def group_by_conditions(claims: list[Claim], keys: set[str]) -> list[tuple[dict[str, str], list[Claim]]]:
    """질문이 말하지 않은 키의 값별로 묶는다.

    전체(`*`) 주장은 어울리는 묶음에 모두 들어가고, 미기재 주장은 키가 빠진 묶음이 된다.
    """
    def stated(claim: Claim) -> dict[str, str]:
        return {key: clean(value) for key, value in claim.conditions.items()
                if key in keys and clean(value) != ANY}

    def is_wide(claim: Claim) -> bool:
        return any(key in keys and clean(value) == ANY for key, value in claim.conditions.items())

    groups: dict[tuple, list[Claim]] = {}
    for claim in claims:
        if not is_wide(claim):
            groups.setdefault(tuple(sorted(stated(claim).items())), []).append(claim)
    for claim in claims:
        if is_wide(claim):
            own = stated(claim)
            fits = [label for label in groups if all(dict(label).get(key) == value for key, value in own.items())]
            for label in fits or [tuple(sorted(own.items()))]:
                groups.setdefault(label, []).append(claim)
    return [(dict(label), groups[label]) for label in sorted(groups)]
