"""팀 기록 저장소. 기록을 넣을 때 인용 검증 → PII 차단 → (구조화) → 관계 판정을 거친다."""
from __future__ import annotations

from . import relation
from typing import Callable

from .pii import PIIGuard
from .schema import Evidence, Record
from .verifier import CitationVerifier


class RecordStore:
    def __init__(self, verifier: CitationVerifier, judge_relations: bool = True,
                 pii_guard: PIIGuard | None = None,
                 structurer: Callable[[Record], None] | None = None):
        self.verifier = verifier
        self.pii_guard = pii_guard
        self.structurer = structurer  # 자유 텍스트 기록 → topic·value·conditions (LLM 모드)
        self.judge_relations = judge_relations
        self.records: dict[str, Record] = {}
        self.version = 0  # 기록이 바뀔 때마다 증가. 답변 캐시 무효화에 쓴다.
        self.log: list[tuple[str, str]] = []  # (기록 id, 대표 관계)

    def add(self, rec: Record) -> str:
        rec.citation_valid = all(self.verifier.verify(e) for e in rec.evidence) if rec.evidence else False
        if self.pii_guard is not None:
            self._mask(rec)
        if self.structurer is not None:
            self.structurer(rec)  # 가린 사본으로 구조화하므로 민감 정보가 외부 LLM에 가지 않는다
        primary = relation.NONE
        if self.judge_relations:
            primary, links = relation.judge(rec, list(self.records.values()))
            rec.relations = links
            for other_id, rel in links:
                self.records[other_id].relations.append((rec.id, rel))
                if rel == relation.CONFLICT:
                    # 양쪽 다 유지하고 검토 요청
                    rec.needs_review = True
                    self.records[other_id].needs_review = True
        self.records[rec.id] = rec
        self.version += 1
        self.log.append((rec.id, primary))
        return primary

    def _mask(self, rec: Record) -> None:
        """인용 검증은 원문 기준으로 끝났으므로 공유되는 사본에서 민감 정보를 가린다."""
        kinds: list[str] = []
        rec.text, k = self.pii_guard.mask(rec.text); kinds += k
        rec.value, k = self.pii_guard.mask(rec.value, deep=False); kinds += k
        masked = []
        for e in rec.evidence:
            quote, k = self.pii_guard.mask(e.quote, deep=False); kinds += k
            masked.append(Evidence(e.source, e.rev, quote))
        rec.evidence = masked
        rec.pii_types = sorted(set(kinds))
        if kinds:
            self.pii_guard.stats["masked_records"] += 1

    def by_topic(self, topic: str) -> list[Record]:
        return [r for r in self.records.values() if r.topic == topic]

    def all(self) -> list[Record]:
        return list(self.records.values())
