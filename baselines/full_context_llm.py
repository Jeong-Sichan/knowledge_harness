"""'LLM vs Ours' 베이스라인: 처리 과정 없이 모든 기록과 원문을 그대로 공통 LLM 답변기에 넣는다.

질문: "정보만 표로 넣어줘도 되는 건 아닌가? 우리 시스템의 처리 과정이 필요한가?"
LLM은 작성자, 승인 상태, 인용, 원문까지 전부 보므로 판단에 필요한 정보는 모두 가진다.
"""
from __future__ import annotations

from pathlib import Path

from harness.context import answer_with_llm, raw_context
from harness.schema import Query, Record, Response
from harness.verifier import SourceStore


class FullContextLLM:
    name = "full_context_llm"

    def __init__(self, sources_dir: str | Path):
        self.sources = SourceStore(sources_dir)
        self.context: list[str] = []

    def ingest(self, records: list[Record]) -> None:
        self.context = raw_context(sorted(records, key=lambda r: r.created_at), self.sources)

    def ask(self, q: Query) -> Response:
        return answer_with_llm(q.question, self.context)
