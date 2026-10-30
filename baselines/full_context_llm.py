"""'LLM vs Ours' 베이스라인: 처리 과정 없이 전체 기록을 표로 넣고 큰 모델이 판단하게 한다.

질문: "정보만 표로 넣어줘도 되는 건 아닌가? 우리 시스템의 처리 과정이 필요한가?"
LLM에게 조건·작성 주체·승인 상태·인용까지 전부 주므로 공정한 비교가 된다.
API 키가 필요하다(ANTHROPIC_API_KEY).
"""
from __future__ import annotations

from harness.schema import STATUSES, Query, Record, Response


class FullContextLLM:
    name = "full_context_llm"

    def __init__(self):
        self.table: list[dict] = []

    def ingest(self, records: list[Record]) -> None:
        self.table = [
            {"id": r.id, "author": r.author, "author_type": r.author_type, "text": r.text,
             "conditions": r.conditions, "status": r.status,
             "evidence": [{"source": e.source, "rev": e.rev, "quote": e.quote} for e in r.evidence]}
            for r in records]

    def ask(self, q: Query) -> Response:
        from harness.llm import full_context_answer

        out = full_context_answer(q.question, self.table)
        status = out.status if out.status in STATUSES else "answered"
        return Response(status, out.supporting_ids, out.team_fact_ids,
                        out.independent_evidence, answer=out.answer)
