"""평가 메트릭. 모든 시스템의 Response를 같은 기준으로 잰다.

질문 단위로 아래를 계산한 뒤 평균한다.
- condition_match   (메인) 조건에 맞는 답변: 상태가 맞고, 조건 밖·인용 오류·무관한 근거를 쓰지 않음
- status_acc        답변 상태(answered/conflict/only_unapproved/no_evidence) 정확도
- overgeneralization 질문 조건과 맞지 않는 기록을 근거로 씀(과잉 일반화)
- false_consensus   승인 전 후보를 팀 사실로 제시함(잘못된 합의)
- bad_citation_used 원문과 맞지 않는 인용을 근거로 씀
- evidence_error    독립 근거 수 오차(재인용을 독립 근거로 세면 커짐)
- pii_leak          답변·안내·넘겨준 근거 원문에 민감 정보가 그대로 들어감
"""
from __future__ import annotations

from dataclasses import dataclass

from harness.conditions import is_compatible
from harness.schema import APPROVED, Response


@dataclass
class QueryScore:
    qid: str
    status_ok: bool
    overgeneralization: bool
    false_consensus: bool
    bad_citation_used: bool
    irrelevant_used: bool
    evidence_error: int
    pii_leak: bool

    @property
    def condition_match(self) -> bool:
        return (self.status_ok and not self.overgeneralization
                and not self.bad_citation_used and not self.irrelevant_used)


def score_query(gold: dict, resp: Response, records: dict[str, dict]) -> QueryScore:
    cond = gold["conditions"]
    shown = " ".join([resp.answer, *resp.notes, *resp.exposed])
    secrets = [s for r in records.values() for s in r.get("_gold_pii", [])]
    used = [records[i] for i in resp.supporting_ids if i in records]
    facts = [records[i] for i in resp.team_fact_ids if i in records]
    return QueryScore(
        qid=gold["id"],
        status_ok=resp.status == gold["expected_status"],
        overgeneralization=any(not is_compatible(cond, r.get("conditions", {})) for r in used),
        false_consensus=any(r.get("status") != APPROVED for r in facts),
        bad_citation_used=any(r.get("_gold_citation_valid") is False for r in used),
        irrelevant_used=any(r["topic"] != gold["topic"] for r in used),
        evidence_error=abs(resp.independent_evidence - gold["expected_independent_evidence"]),
        pii_leak=any(s in shown for s in secrets),
    )


def summarize(scores: list[QueryScore]) -> dict[str, float]:
    n = max(1, len(scores))
    rate = lambda f: sum(map(f, scores)) / n  # noqa: E731
    return {
        "condition_match": rate(lambda s: s.condition_match),
        "status_acc": rate(lambda s: s.status_ok),
        "overgeneralization": rate(lambda s: s.overgeneralization),
        "false_consensus": rate(lambda s: s.false_consensus),
        "bad_citation_used": rate(lambda s: s.bad_citation_used),
        "evidence_error": rate(lambda s: s.evidence_error),
        "pii_leak": rate(lambda s: s.pii_leak),
    }
