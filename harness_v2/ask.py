"""D8 ②~④ 질문 처리의 규칙 부분. 해석이 끝난 주제 하나의 주장을 거르고 상태를 정한다."""
from __future__ import annotations

from dataclasses import dataclass, field

from .approval import APPROVED, CORRECTED, REJECTED, SUPERSEDED, approvers, claim_states
from .conditions import MISMATCH, UNVERIFIED, clean, compare, group_by_conditions, nearest, relevant_keys
from .model import Claim, Vote
from .quote import find_quote
from .relations import independent_count

ANSWERED = "answered"
CONFLICT = "conflict"
ONLY_UNAPPROVED = "only_unapproved"
NO_EVIDENCE = "no_evidence"
BY_CONDITION = "by_condition"
HISTORY = "history"
SOURCE_CONFIRMED = "confirmed"
SOURCE_MISSING = "missing"


@dataclass
class Entry:
    claim: Claim
    state: str
    approvers: list[str]
    unverified: bool = False
    previous: bool = False
    source: str | None = None


@dataclass
class Group:
    conditions: dict[str, str]
    status: str
    entries: list[Entry]
    independent: int = 0


@dataclass
class TopicResult:
    status: str
    groups: list[Group] = field(default_factory=list)
    previous: list[Claim] = field(default_factory=list)
    different_conditions: list[Claim] = field(default_factory=list)
    ignored_keys: list[str] = field(default_factory=list)


def group_status(entries: list[Entry]) -> tuple[str, int]:
    """(상태, 독립 근거 수). 조건이 확인된 주장이 있으면 그것으로 정하고, 이전 결정은 값 비교에서 뺀다."""
    live = [entry for entry in entries if not entry.previous] or entries
    basis = [entry for entry in live if not entry.unverified] or live
    kinds = {entry.claim.kind for entry in basis}
    if any(len({clean(entry.claim.value) for entry in basis if entry.claim.kind == kind}) > 1 for kind in kinds):
        return CONFLICT, 0
    approved = [entry.claim for entry in basis if entry.state == APPROVED or entry.previous]
    return (ANSWERED, independent_count(approved)) if approved else (ONLY_UNAPPROVED, 0)


def source_check(claim: Claim, latest: dict[str, str]) -> str | None:
    """인용이 최신 원문에도 있는지 본다. 최신 원문을 못 받은 인용은 판단하지 않는다."""
    known = [item for item in claim.evidence if item.doc in latest]
    if not known:
        return None
    return SOURCE_CONFIRMED if all(find_quote(latest[item.doc], item.quote).ok for item in known) else SOURCE_MISSING


def evaluate(topic: str, claims: list[Claim], votes: list[Vote], question: dict[str, str] | None = None,
             time: str = "current", latest: dict[str, str] | None = None) -> TopicResult:
    """claims는 별칭을 적용한 전체 주장이다. 주제의 주장을 전부 모은 뒤 거른다."""
    question, latest = question or {}, latest or {}
    states = claim_states(claims, votes)
    mine = [claim for claim in claims if claim.topic == topic]
    relevant = relevant_keys(mine)
    live = [claim for claim in mine if states[claim.id] != REJECTED]
    verdicts = {claim.id: compare(question, claim.conditions, relevant) for claim in live}

    def replaced(claim: Claim) -> bool:
        return states[claim.id] in (SUPERSEDED, CORRECTED)

    fitting = [claim for claim in live if verdicts[claim.id] != MISMATCH]
    different = [claim for claim in live if verdicts[claim.id] == MISMATCH and not replaced(claim)]
    kept = fitting if time == HISTORY else [claim for claim in fitting if not replaced(claim)]
    unstated = relevant - question.keys()
    result = TopicResult(NO_EVIDENCE, different_conditions=nearest(question, different),
                         previous=[] if time == HISTORY else [claim for claim in fitting if replaced(claim)],
                         ignored_keys=sorted(question.keys() - relevant))
    for conditions, members in group_by_conditions(kept, unstated):
        entries = [Entry(claim, states[claim.id], approvers(claim, votes),
                         verdicts[claim.id] == UNVERIFIED or any(key not in claim.conditions for key in unstated),
                         replaced(claim), source_check(claim, latest)) for claim in members]
        status, independent = group_status(entries)
        result.groups.append(Group(conditions, status, entries, independent))
    if result.groups:
        result.status = result.groups[0].status if len(result.groups) == 1 else BY_CONDITION
    return result
