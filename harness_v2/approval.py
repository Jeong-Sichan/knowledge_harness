"""D7 승인 상태 계산. 투표와 관계로 매번 계산하고 저장하지 않는다."""
from __future__ import annotations

from collections.abc import Collection

from .model import APPROVE, DECISION, REJECT, Claim, Vote
from .relations import CONFLICT, is_earlier, narrows, relation

CANDIDATE = "candidate"
APPROVED = "approved"
REJECTED = "rejected"
SUPERSEDED = "superseded"
CORRECTED = "corrected"


def required_voters(claim: Claim, claims: list[Claim], gone: Collection[str] = ()) -> set[str]:
    """작성자 본인 + 정정 대상 작성자 + 충돌한 옛 주장 작성자. 동시 제출이면 서로 승인한다.

    gone은 이미 거절·대체·정정된 주장 id다. 이런 주장과의 충돌은 승인을 요구하지 않는다.
    """
    needed = {claim.author}
    for other in claims:
        if other.id == claim.id:
            continue
        conflicts = other.id not in gone and relation(claim, other) == CONFLICT and not is_earlier(claim, other)
        if claim.corrects == other.id or conflicts:
            needed.add(other.author)
    return needed


def last_votes(votes: list[Vote]) -> dict[tuple[str, str], str]:
    """한 사람의 투표는 시간상 마지막 것만 유효하다."""
    return {(vote.claim, vote.voter): vote.decision for vote in sorted(votes, key=lambda vote: vote.at)}


def approvers(claim: Claim, votes: list[Vote]) -> list[str]:
    return sorted(voter for (target, voter), decision in last_votes(votes).items()
                  if target == claim.id and decision == APPROVE)


def replaced_by(approved: list[Claim], claims: list[Claim]) -> dict[str, str]:
    """승인된 주장이 밀어낸 옛 주장의 상태. 좁은 결정은 넓은 결정을 대체하지 않는다."""
    replaced = {}
    for new in approved:
        for old in claims:
            if new.corrects == old.id:
                replaced[old.id] = CORRECTED
            elif (new.kind == DECISION and relation(new, old) == CONFLICT
                  and is_earlier(old, new) and not narrows(new, old)):
                replaced.setdefault(old.id, SUPERSEDED)
    return replaced


def claim_states(claims: list[Claim], votes: list[Vote]) -> dict[str, str]:
    """거절을 먼저 정하고, 승인과 대체는 더 바뀌지 않을 때까지 계산한다.

    밀려난 주장이 늘면 필요한 승인이 줄어 승인만 늘어나므로 반복은 끝난다.
    주장 순서는 결과를 바꾸지 않는다.
    """
    last = last_votes(votes)
    rejected = {claim.id for claim in claims
                if any(last.get((claim.id, voter)) == REJECT for voter in required_voters(claim, claims))}
    replaced: dict[str, str] = {}
    while True:
        gone = rejected | replaced.keys()
        approved = [claim for claim in claims if claim.id not in rejected
                    and all(last.get((claim.id, voter)) == APPROVE for voter in required_voters(claim, claims, gone))]
        found = replaced_by(approved, claims)
        if found == replaced:
            break
        replaced = found
    approved_ids = {claim.id for claim in approved}
    return {claim.id: (REJECTED if claim.id in rejected else replaced.get(claim.id)
                       or (APPROVED if claim.id in approved_ids else CANDIDATE)) for claim in claims}
