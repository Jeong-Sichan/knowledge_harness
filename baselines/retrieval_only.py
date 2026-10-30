"""약한 베이스라인: 일반적인 RAG. 질문과 비슷한 기록을 찾아서 그대로 근거로 쓴다.

조건, 작성 주체, 승인 상태, 재인용을 구분하는 처리가 없다. 우리 하네스가 없을 때의 기본 동작이다.
answerer="llm"이면 찾은 기록과 원문을 공통 LLM 답변기에 넘긴다.
"""
from __future__ import annotations

from pathlib import Path

from harness.context import answer_with_llm, raw_context
from harness.retriever import bm25_top_k
from harness.schema import ANSWERED, NO_EVIDENCE, Query, Record, Response
from harness.verifier import SourceStore


class RetrievalOnly:
    name = "retrieval_only"

    def __init__(self, sources_dir: str | Path | None = None, answerer: str = "rule", k: int | None = None):
        self.answerer = answerer
        self.k = k or (5 if answerer == "llm" else 3)
        self.sources = SourceStore(sources_dir) if sources_dir else None
        self.records: list[Record] = []

    def ingest(self, records: list[Record]) -> None:
        self.records = list(records)

    def ask(self, q: Query) -> Response:
        hits = bm25_top_k(self.records, q.question, self.k)
        if self.answerer == "llm":
            return answer_with_llm(q.question, raw_context(hits, self.sources))
        if not hits:
            return Response(NO_EVIDENCE, [], [], 0, answer="관련 기록이 없습니다.")
        ids = [r.id for r in hits]
        return Response(ANSWERED, ids, ids, len(hits),
                        answer=f"{hits[0].value} (관련 기록 {len(hits)}건)",
                        exposed=[r.text for r in hits])
