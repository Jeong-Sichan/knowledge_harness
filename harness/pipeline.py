"""하네스 파이프라인: 기록 입력 → (구조화) → 인용 검증 → PII 차단 → 관계 판정 → 저장 / 질문 → 검색 → 답변 구성."""
from __future__ import annotations

from pathlib import Path

from .answer import ComposerConfig, compose
from .pii import PIIGuard
from .retriever import Retriever
from .schema import Query, Record, Response
from .store import RecordStore
from .verifier import CitationVerifier, SourceStore


class Harness:
    name = "harness"

    def __init__(self, sources_dir: str | Path, cfg: ComposerConfig | None = None,
                 llm_judge=None, use_cache: bool = True, use_pii: bool = True):
        self.cfg = cfg or ComposerConfig()
        self.verifier = CitationVerifier(SourceStore(sources_dir), llm_judge=llm_judge)
        self.pii_guard = PIIGuard() if use_pii else None
        self.store = RecordStore(self.verifier, pii_guard=self.pii_guard)
        self.retriever = Retriever()
        self.use_cache = use_cache
        # 답변 캐시: (topic, 조건, 저장소 버전)이 같으면 같은 답. 기록이 추가되면 버전이 바뀌어 자동 무효화.
        self._answer_cache: dict[tuple, Response] = {}
        self.stats = {"queries": 0, "answer_cache_hits": 0}

    def ingest(self, records: list[Record]) -> None:
        for r in sorted(records, key=lambda r: r.created_at):
            self.store.add(r)

    def ask(self, q: Query) -> Response:
        self.stats["queries"] += 1
        key = None
        if self.use_cache and q.topic:
            key = (q.topic, tuple(sorted(q.conditions.items())), self.store.version)
            if key in self._answer_cache:
                self.stats["answer_cache_hits"] += 1
                return self._answer_cache[key]
        candidates = self.retriever.retrieve(self.store.all(), q)
        resp = compose(q, candidates, self.cfg)
        if key is not None:
            self._answer_cache[key] = resp
        return resp
