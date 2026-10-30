"""팀 기록 저장소. 기록을 넣을 때 인용 검증과 관계 판정을 거친다."""
from __future__ import annotations

from . import relation
from .schema import Record
from .verifier import CitationVerifier


class RecordStore:
    def __init__(self, verifier: CitationVerifier, judge_relations: bool = True):
        self.verifier = verifier
        self.judge_relations = judge_relations
        self.records: dict[str, Record] = {}
        self.version = 0  # 기록이 바뀔 때마다 증가. 답변 캐시 무효화에 쓴다.
        self.log: list[tuple[str, str]] = []  # (기록 id, 대표 관계)

    def add(self, rec: Record) -> str:
        rec.citation_valid = all(self.verifier.verify(e) for e in rec.evidence) if rec.evidence else False
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

    def by_topic(self, topic: str) -> list[Record]:
        return [r for r in self.records.values() if r.topic == topic]

    def all(self) -> list[Record]:
        return list(self.records.values())
