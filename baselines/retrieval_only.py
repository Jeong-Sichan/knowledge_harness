"""약한 베이스라인: 일반적인 RAG. 질문과 비슷한 기록을 찾아서 그대로 근거로 쓴다.

조건, 작성 주체, 승인 상태, 재인용을 구분하지 않는다. 우리 하네스가 없을 때의 기본 동작이다.
"""
from __future__ import annotations

from harness.retriever import bm25_top_k
from harness.schema import ANSWERED, NO_EVIDENCE, Query, Record, Response


class RetrievalOnly:
    name = "retrieval_only"

    def __init__(self, k: int = 3):
        self.k = k
        self.records: list[Record] = []

    def ingest(self, records: list[Record]) -> None:
        self.records = list(records)

    def ask(self, q: Query) -> Response:
        hits = bm25_top_k(self.records, q.question, self.k)
        if not hits:
            return Response(NO_EVIDENCE, [], [], 0, answer="관련 기록이 없습니다.")
        ids = [r.id for r in hits]
        return Response(ANSWERED, ids, ids, len(hits),
                        answer=f"{hits[0].value} (관련 기록 {len(hits)}건)")
