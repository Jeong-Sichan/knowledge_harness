"""D2 저장 객체. 상태와 관계는 저장하지 않고 매번 계산한다."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

OBSERVATION = "observation"
DECISION = "decision"
APPROVE = "approve"
REJECT = "reject"


@dataclass(frozen=True)
class Source:
    id: str
    doc: str
    rev: int
    author: str
    text: str
    location: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class Evidence:
    doc: str
    start: int
    end: int
    quote: str = ""


@dataclass(frozen=True)
class Claim:
    id: str
    kind: str
    topic: str
    value: str
    author: str
    conditions: dict[str, str] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    corrects: str | None = None
    seen: tuple[str, ...] = ()
    statement: str = ""
    written_by: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Vote:
    claim: str
    voter: str
    decision: str
    at: str


def apply_aliases(claims: list[Claim], topics: dict[str, str] | None = None,
                  keys: dict[str, str] | None = None) -> list[Claim]:
    """별칭을 대표 이름으로 바꾼다. 이후 단계는 대표 이름만 본다."""
    topics, keys = topics or {}, keys or {}
    return [replace(claim, topic=topics.get(claim.topic, claim.topic),
                    conditions={keys.get(key, key): value for key, value in claim.conditions.items()})
            for claim in claims]
