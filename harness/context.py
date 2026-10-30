"""답변기에 넘길 맥락 만들기.

모든 시스템이 같은 원재료(기록 + 원문 문서)를 받는다.
- raw_context: 가공 없는 기록과 원문. 베이스라인이 쓴다.
- harness_context: 하네스가 걸러내고 판정한 결과. 우리 시스템이 쓴다.
"""
from __future__ import annotations

from .conditions import describe
from .schema import Record, Response
from .verifier import SourceStore


def _evidence(r: Record) -> str:
    return "; ".join(f"{e.source} rev{e.rev} \"{e.quote}\"" for e in r.evidence)


def raw_line(r: Record) -> str:
    """팀 기록 원본 한 줄. 조건 필드는 넣지 않는다(조건은 기록 문장과 원문에서 읽어야 함)."""
    return (f"[{r.id}] 작성자: {r.author}({r.author_type}) | 상태: {r.status} | 작성일: {r.created_at} "
            f"| 주장: {r.text} | 근거: {_evidence(r)}")


def source_block(source: str, sources: SourceStore) -> str:
    text = sources.get(source, 1) or "(원문 없음)"
    return f"<source id=\"{source}\">\n{text.strip()}\n</source>"


def raw_context(records: list[Record], sources: SourceStore) -> list[str]:
    """기록 줄 + 기록이 인용한 원문 문서(중복 제거)."""
    lines = [raw_line(r) for r in records]
    seen: list[str] = []
    for r in records:
        for e in r.evidence:
            if e.source not in seen:
                seen.append(e.source)
    return lines + [source_block(s, sources) for s in seen]


def harness_context(resp: Response, records: dict[str, Record]) -> list[str]:
    """하네스 판정 + 조건에 맞고 검증된 기록(민감 정보 가림)."""
    lines = [f"[하네스 판정] {resp.status}: {resp.answer}"]
    lines += [f"[하네스 안내] {n}" for n in resp.notes]
    for rid in resp.supporting_ids:
        r = records[rid]
        lines.append(
            f"[{r.id}] 작성자: {r.author}({r.author_type}) | 상태: {r.status} | 조건: {describe(r.conditions)} "
            f"| 주장: {r.text} | 근거(원문 대조 완료): {_evidence(r)}")
    return lines


def answer_with_llm(question: str, context: list[str], notes: list[str] | None = None) -> Response:
    """공통 답변기 호출. 넘긴 맥락 전체가 사용자의 AI에게 노출된 것으로 본다(exposed)."""
    from . import llm

    out = llm.answer(question, context)
    return Response(out.status, out.supporting_ids, out.team_fact_ids, out.independent_evidence,
                    answer=out.answer, notes=list(notes or []), exposed=list(context))
