"""하네스 파이프라인: 기록 입력 → 인용 검증 → PII 차단 → (구조화) → 관계 판정 → 저장 / 질문 → (파싱) → 검색 → 답변 구성.

모드
- structure="gold": 기록·질문이 이미 구조화되어 있다고 본다(모듈 개발·ablation용, 오프라인)
- structure="llm":  자유 텍스트 기록과 질문 문장만으로 시작한다(베이스라인과 공정 비교용)
- answerer="rule":  템플릿 답변
- answerer="llm":   모든 시스템이 공유하는 LLM 답변기에 하네스 맥락을 넘긴다
"""
from __future__ import annotations

from pathlib import Path

from .answer import ComposerConfig, compose
from .context import answer_with_llm, harness_context
from .pii import PIIGuard
from .retriever import Retriever
from .schema import Query, Record, Response
from .store import RecordStore
from .verifier import CitationVerifier, SourceStore


class Harness:
    name = "harness"

    def __init__(self, sources_dir: str | Path, cfg: ComposerConfig | None = None,
                 llm_judge=None, use_cache: bool = True, use_pii: bool = True,
                 structure: str = "gold", answerer: str = "rule"):
        self.cfg = cfg or ComposerConfig()
        self.structure, self.answerer = structure, answerer
        self.sources = SourceStore(sources_dir)
        self.verifier = CitationVerifier(self.sources, llm_judge=llm_judge)
        self.pii_guard = None
        if use_pii:
            detector = None
            if structure == "llm":
                from .llm import detect_pii_spans
                detector = detect_pii_spans  # 실명처럼 형식 없는 정보는 작은 모델로
            self.pii_guard = PIIGuard(llm_detector=detector)
        self.store = RecordStore(self.verifier, pii_guard=self.pii_guard,
                                 structurer=self._structure if structure == "llm" else None)
        self.retriever = Retriever()
        self.use_cache = use_cache
        # 답변 캐시: (topic, 조건, 저장소 버전)이 같으면 같은 답. 기록이 추가되면 버전이 바뀌어 자동 무효화.
        self._answer_cache: dict[tuple, Response] = {}
        self.stats = {"queries": 0, "answer_cache_hits": 0}

    def _structure(self, rec: Record) -> None:
        from .llm import structure_record

        known: dict[str, list[str]] = {}
        for r in self.store.all():
            values = known.setdefault(r.topic, [])
            if r.value not in values:
                values.append(r.value)
        source = "\n".join(self.sources.get(e.source, e.rev) or "" for e in rec.evidence)
        if self.pii_guard is not None:
            source, _ = self.pii_guard.mask(source)
        rec.topic, rec.value, rec.conditions = structure_record(rec.text, source, known)

    def ingest(self, records: list[Record]) -> None:
        for r in sorted(records, key=lambda r: r.created_at):
            self.store.add(r)

    def ask(self, q: Query) -> Response:
        self.stats["queries"] += 1
        if self.structure == "llm":
            from .llm import parse_query

            topic, cond = parse_query(q.question, sorted({r.topic for r in self.store.all()}))
            q = Query(q.id, q.question, topic, cond)
        key = None
        if self.use_cache and q.topic:
            key = (q.topic, tuple(sorted(q.conditions.items())), self.store.version, q.question)
            if key in self._answer_cache:
                self.stats["answer_cache_hits"] += 1
                return self._answer_cache[key]
        candidates = self.retriever.retrieve(self.store.all(), q)
        resp = compose(q, candidates, self.cfg)
        if self.answerer == "llm":
            resp = answer_with_llm(q.question, harness_context(resp, self.store.records), resp.notes)
        if key is not None:
            self._answer_cache[key] = resp
        return resp
