"""답변 구성 모듈(Answer Composer): 근거 묶음을 상태(status)와 함께 답으로 만든다.

목표는 AI가 확실히 답할 수 있는 부분과 아닌 부분을 구분해서 답하게 하는 것이다.
지금은 템플릿으로 답을 만들고, 최종 문장 생성은 LLM으로 바꿀 수 있다(같은 근거 묶음을 프롬프트로 넘김).
"""
from __future__ import annotations

from dataclasses import dataclass

from .conditions import describe, is_compatible, mismatched_keys
from .schema import (ANSWERED, APPROVED, CONFLICT, NO_EVIDENCE, ONLY_UNAPPROVED,
                     Query, Record, Response)


@dataclass
class ComposerConfig:
    """모듈별 기여를 보는 ablation 스위치."""
    use_conditions: bool = True  # 조건 비교
    use_verifier: bool = True    # 인용 검증 결과 반영
    use_dedup: bool = True       # 재인용을 같은 근거로 묶기
    use_approval: bool = True    # 승인/후보 상태 구분


def compose(q: Query, candidates: list[Record], cfg: ComposerConfig = ComposerConfig()) -> Response:
    notes: list[str] = []

    if cfg.use_conditions:
        compatible = [r for r in candidates if is_compatible(q.conditions, r.conditions)]
        nearby = [r for r in candidates if r not in compatible]
    else:
        compatible, nearby = list(candidates), []

    if cfg.use_verifier:
        bad = [r for r in compatible if not r.citation_valid]
        applicable = [r for r in compatible if r.citation_valid]
        for r in bad:
            notes.append(f"{r.id}: 인용이 원문과 맞지 않아 근거에서 제외")
    else:
        applicable = compatible

    if not applicable:
        for r in nearby:
            keys = mismatched_keys(q.conditions, r.conditions)
            notes.append(f"{r.id}({r.value})는 조건이 다름: " + ", ".join(
                f"{k} 질문={q.conditions[k]} / 기록={r.conditions[k]}" for k in keys))
        return Response(
            status=NO_EVIDENCE, supporting_ids=[], team_fact_ids=[], independent_evidence=0,
            answer=f"[{describe(q.conditions)}] 조건에 맞는 팀 근거가 없습니다."
                   + (" 다른 조건의 기록만 있습니다." if nearby else ""),
            notes=notes)

    approved = [r for r in applicable if r.status == APPROVED] if cfg.use_approval else applicable
    if cfg.use_dedup:
        independent = len({e.key for r in applicable for e in r.evidence})
    else:
        independent = sum(len(r.evidence) for r in applicable)

    values = sorted({r.value for r in applicable})
    if len(values) > 1:
        status = CONFLICT
        sides = "; ".join(
            f"{v}: " + ", ".join(f"{r.id}({'승인' if r.status == APPROVED else '후보'}, {r.author})"
                               for r in applicable if r.value == v)
            for v in values)
        text = f"같은 조건에서 주장이 엇갈립니다 → {sides}. 팀 검토가 필요합니다."
    elif cfg.use_approval and not approved:
        status = ONLY_UNAPPROVED
        text = (f"'{values[0]}' 기록이 있지만 아직 팀 승인 전 후보입니다"
                f"(작성: {', '.join(sorted({r.author for r in applicable}))}). 팀 사실로 보기 어렵습니다.")
    else:
        status = ANSWERED
        text = f"{values[0]} (승인된 팀 근거 {len(approved)}건, 독립 근거 {independent}개)"

    if cfg.use_dedup:
        dup = sum(len(r.evidence) for r in applicable) - independent
        if dup > 0:
            notes.append(f"재인용 {dup}건은 같은 근거로 묶음")

    return Response(status=status, supporting_ids=[r.id for r in applicable],
                    team_fact_ids=[r.id for r in approved], independent_evidence=independent,
                    answer=f"[{describe(q.conditions)}] {text}", notes=notes)
