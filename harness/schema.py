"""하네스 전체에서 쓰는 데이터 구조."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 기록 승인 상태
CANDIDATE = "candidate"  # 개인/AI가 올린 공유 후보
APPROVED = "approved"    # 팀 합의를 거쳐 승격된 팀 주장

# 답변 상태
ANSWERED = "answered"                # 조건에 맞는 승인 근거로 답할 수 있음
CONFLICT = "conflict"                # 같은 조건에서 서로 다른 주장이 공존
ONLY_UNAPPROVED = "only_unapproved"  # 근거가 미승인 후보뿐
NO_EVIDENCE = "no_evidence"          # 질문 조건에 맞는 근거 없음
STATUSES = (ANSWERED, CONFLICT, ONLY_UNAPPROVED, NO_EVIDENCE)


@dataclass(frozen=True)
class Evidence:
    source: str  # 원문 문서 id (예: exp_001)
    rev: int     # 원문 버전
    quote: str   # 인용 구간

    @property
    def key(self) -> tuple[str, int, str]:
        """같은 원문·버전·구간이면 같은 근거로 본다."""
        return (self.source, self.rev, " ".join(self.quote.split()))


@dataclass
class Record:
    id: str
    created_at: str
    author: str
    author_type: str  # human | ai
    text: str
    topic: str
    value: str
    conditions: dict[str, Any]
    evidence: list[Evidence]
    status: str = CANDIDATE
    # 하네스가 채우는 필드
    citation_valid: bool | None = None
    relations: list[tuple[str, str]] = field(default_factory=list)  # (상대 기록 id, 관계)
    needs_review: bool = False
    pii_types: list[str] = field(default_factory=list)  # 가린 민감 정보 종류

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Record":
        return cls(
            id=d["id"],
            created_at=d["created_at"],
            author=d["author"],
            author_type=d["author_type"],
            text=d["text"],
            topic=d["topic"],
            value=str(d["value"]),
            conditions=dict(d.get("conditions", {})),
            evidence=[Evidence(**e) for e in d.get("evidence", [])],
            status=d.get("status", CANDIDATE),
        )


@dataclass
class Query:
    id: str
    question: str
    topic: str | None = None
    conditions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Query":
        return cls(id=d["id"], question=d["question"], topic=d.get("topic"),
                   conditions=dict(d.get("conditions", {})))


@dataclass
class Response:
    """모든 시스템(우리 하네스, 베이스라인)이 같은 형식으로 답하게 해서 같은 메트릭으로 잰다."""
    status: str
    supporting_ids: list[str]   # 답의 근거로 제시한 기록
    team_fact_ids: list[str]    # 그중 '팀이 합의한 사실'로 제시한 기록
    independent_evidence: int   # 답변이 주장하는 독립 근거 수
    answer: str = ""
    notes: list[str] = field(default_factory=list)  # 조건 차이, 충돌, 인용 오류 등 안내
    exposed: list[str] = field(default_factory=list)  # 사용자(와 그의 AI)에게 넘어가는 근거 원문
