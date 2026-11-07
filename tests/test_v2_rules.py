"""D15 1층 규칙 부품 테스트: 조건 비교(D5), 관계(D6), 승인(D7), 상태(D8), 앞뒤 순서(D12)."""
from harness_v2.approval import (APPROVED, CANDIDATE, CORRECTED, REJECTED, SUPERSEDED, approvers, claim_states,
                                 required_voters)
from harness_v2.ask import (ANSWERED, BY_CONDITION, CONFLICT, HISTORY, NO_EVIDENCE, ONLY_UNAPPROVED, SOURCE_CONFIRMED,
                            SOURCE_MISSING, evaluate)
from harness_v2.conditions import MATCH, MISMATCH, UNVERIFIED, compare, group_by_conditions, nearest, relevant_keys
from harness_v2.model import APPROVE, DECISION, OBSERVATION, REJECT, Claim, Evidence, Vote, apply_aliases
from harness_v2.relations import (CONDITION_DIFFERS, CORRECTION, NEEDS_COMPARISON, NONE, RECITATION, SUPPORT,
                                  independent_count, is_concurrent, is_earlier, relation)
from harness_v2.relations import CONFLICT as REL_CONFLICT

_next_span = iter(range(0, 100000, 100))


def make(id, value="x", kind=OBSERVATION, topic="t", author="a", conditions=None, span=None, doc=None, **rest):
    """인용을 따로 주지 않으면 서로 겹치지 않는 구간을 쓴다."""
    start = next(_next_span) if span is None else span[0]
    end = start + 10 if span is None else span[1]
    evidence = (Evidence(doc or "doc", start, end, rest.pop("quote", "")),)
    return Claim(id, kind, topic, value, author, conditions or {}, evidence, **rest)


def yes(claim, *voters, at="1"):
    return [Vote(claim, voter, APPROVE, at) for voter in voters]


# D5 ③ 표의 6가지 경우

def test_d5_same_value_matches():
    assert compare({"n": "12"}, {"n": "12"}, {"n"}) == MATCH


def test_d5_value_cleanup_ignores_case_and_spacing():
    assert compare({"data": "V1  set"}, {"data": "v1 set"}, {"data"}) == MATCH


def test_d5_different_value_is_excluded_and_nearest_is_listed():
    assert compare({"n": "12"}, {"n": "40"}, {"n"}) == MISMATCH
    result = evaluate("t", [make("c1", conditions={"n": "40"})], yes("c1", "a"), {"n": "12"})
    assert result.status == NO_EVIDENCE
    assert [claim.id for claim in result.different_conditions] == ["c1"]


def test_d5_nearest_keeps_three_with_fewest_differences():
    question = {"a": "1", "b": "2"}
    far = make("a_far", conditions={"a": "9", "b": "9"})
    close = [make(f"c{i}", conditions={"a": "9", "b": "2"}) for i in range(3)]
    assert [claim.id for claim in nearest(question, [far, *close])] == ["c0", "c1", "c2"]


def test_d5_any_matches_every_value():
    assert compare({"n": "12"}, {"n": "*"}, {"n"}) == MATCH


def test_d5_missing_relevant_key_is_included_as_unverified():
    assert compare({"n": "12"}, {}, {"n"}) == UNVERIFIED
    claims = [make("c1", conditions={"n": "40"}), make("c2", "y")]
    result = evaluate("t", claims, yes("c2", "a"), {"n": "12"})
    assert result.status == ANSWERED
    assert result.groups[0].entries[0].unverified


def test_d5_unrelated_question_key_is_ignored():
    assert compare({"color": "red"}, {"n": "12"}, {"n"}) == MATCH
    result = evaluate("t", [make("c1", conditions={"n": "12"})], yes("c1", "a"), {"color": "red", "n": "12"})
    assert result.status == ANSWERED
    assert result.ignored_keys == ["color"]


def test_d5_unstated_relevant_key_groups_by_condition():
    claims = [make("c1", "x", conditions={"n": "12"}), make("c2", "y", conditions={"n": "40"})]
    result = evaluate("t", claims, yes("c1", "a") + yes("c2", "a"))
    assert result.status == BY_CONDITION
    assert [(group.conditions, group.status) for group in result.groups] == [
        ({"n": "12"}, ANSWERED), ({"n": "40"}, ANSWERED)]


def test_d5_relevant_keys_come_from_all_claims_of_the_topic():
    assert relevant_keys([make("c1", conditions={"a": "1"}), make("c2", conditions={"b": "2"})]) == {"a", "b"}


def test_d5_groups_put_any_in_each_value_and_missing_apart():
    claims = [make("v1", conditions={"n": "12"}), make("v2", conditions={"n": "40"}),
              make("all", conditions={"n": "*"}), make("none")]
    groups = {tuple(label.items()): [claim.id for claim in members]
              for label, members in group_by_conditions(claims, {"n"})}
    assert groups == {(): ["none", "all"], (("n", "12"),): ["v1", "all"], (("n", "40"),): ["v2", "all"]}


# D6 ② 표

def test_d6_different_topic_or_kind_is_not_compared():
    assert relation(make("a", topic="p"), make("b", topic="q")) == NONE
    assert relation(make("a", kind=DECISION), make("b", kind=OBSERVATION)) == NONE


def test_d6_overlapping_quote_is_recitation():
    assert relation(make("a", span=(10, 20)), make("b", span=(15, 30))) == RECITATION


def test_d6_touching_quotes_do_not_overlap():
    assert relation(make("a", "1", span=(10, 20)), make("b", "1", span=(20, 30))) == SUPPORT


def test_d6_same_span_in_another_document_is_not_recitation():
    assert relation(make("a", "1", span=(10, 20)), make("b", "1", span=(10, 20), doc="other")) == SUPPORT


def test_d6_correction():
    assert relation(make("new", "2", corrects="old"), make("old", "1")) == CORRECTION


def test_d6_different_condition():
    assert relation(make("a", "1", conditions={"n": "12"}), make("b", "2", conditions={"n": "40"})) == CONDITION_DIFFERS


def test_d6_one_side_missing_needs_comparison():
    assert relation(make("a", "1", conditions={"n": "12"}), make("b", "2")) == NEEDS_COMPARISON


def test_d6_different_value_wins_over_missing_key():
    new = make("a", "1", conditions={"n": "12", "k": "5"})
    assert relation(new, make("b", "2", conditions={"n": "40"})) == CONDITION_DIFFERS


def test_d6_support():
    assert relation(make("a", "1"), make("b", " 1 ")) == SUPPORT


def test_d6_conflict_for_observation_and_decision():
    assert relation(make("a", "1"), make("b", "2")) == REL_CONFLICT
    assert relation(make("a", "1", kind=DECISION), make("b", "2", kind=DECISION)) == REL_CONFLICT


def test_d6_any_counts_as_same_condition():
    assert relation(make("a", "1", conditions={"n": "*"}), make("b", "2", conditions={"n": "12"})) == REL_CONFLICT


def test_d6_decision_change_needs_old_author_then_replaces_old():
    old = make("old", "median", DECISION, author="park")
    new = make("new", "knn", DECISION, author="jung", seen=("old",))
    claims = [old, new]
    assert required_voters(new, claims) == {"jung", "park"}
    votes = yes("old", "park") + yes("new", "jung")
    assert claim_states(claims, votes)["new"] == CANDIDATE
    states = claim_states(claims, votes + yes("new", "park"))
    assert (states["old"], states["new"]) == (SUPERSEDED, APPROVED)


def test_d6_old_author_rejecting_keeps_old_decision():
    old = make("old", "median", DECISION, author="park")
    new = make("new", "knn", DECISION, author="jung", seen=("old",))
    votes = yes("old", "park") + yes("new", "jung") + [Vote("new", "park", REJECT, "2")]
    states = claim_states([old, new], votes)
    assert (states["old"], states["new"]) == (APPROVED, REJECTED)
    assert evaluate("t", [old, new], votes).status == ANSWERED


def test_d6_own_decision_changes_with_own_approval():
    old = make("old", "1", DECISION)
    new = make("new", "2", DECISION, seen=("old",))
    assert claim_states([old, new], yes("old", "a") + yes("new", "a"))["old"] == SUPERSEDED


def test_d6_pending_decision_conflict_shows_both():
    old = make("old", "median", DECISION, author="park")
    new = make("new", "knn", DECISION, author="jung", seen=("old",))
    result = evaluate("t", [old, new], yes("old", "park"))
    assert result.status == CONFLICT
    assert {entry.claim.id for entry in result.groups[0].entries} == {"old", "new"}


def test_d6_approved_observation_conflict_keeps_both():
    old = make("old", "1", author="park")
    new = make("new", "2", author="jung", seen=("old",))
    votes = yes("old", "park") + yes("new", "jung", "park")
    assert claim_states([old, new], votes) == {"old": APPROVED, "new": APPROVED}
    assert evaluate("t", [old, new], votes).status == CONFLICT


def test_d6_rejected_observation_leaves_old():
    old = make("old", "1", author="park")
    new = make("new", "2", author="jung", seen=("old",))
    votes = yes("old", "park") + yes("new", "jung") + [Vote("new", "park", REJECT, "2")]
    assert claim_states([old, new], votes)["new"] == REJECTED


def test_d6_correcting_someone_else_needs_their_approval():
    old = make("old", "1", author="park")
    new = make("new", "2", author="jung", corrects="old", seen=("old",))
    assert required_voters(new, [old, new]) == {"jung", "park"}
    assert claim_states([old, new], yes("old", "park") + yes("new", "jung"))["old"] == APPROVED
    assert claim_states([old, new], yes("old", "park") + yes("new", "jung", "park"))["old"] == CORRECTED


def test_d6_correction_with_the_same_quote_is_a_correction():
    old = make("old", "1", span=(0, 10))
    new = make("new", "2", span=(0, 10), corrects="old", seen=("old",))
    assert relation(new, old) == CORRECTION
    assert claim_states([old, new], yes("old", "a") + yes("new", "a"))["old"] == CORRECTED


def test_d6_correction_keeping_value_and_quote_still_corrects():
    old = make("old", "1", span=(0, 10), conditions={"n": "12"})
    new = make("new", "1", span=(0, 10), conditions={"n": "40"}, corrects="old", seen=("old",))
    assert relation(new, old) == RECITATION
    assert claim_states([old, new], yes("old", "a") + yes("new", "a"))["old"] == CORRECTED


def test_d6_same_quote_with_another_value_is_a_conflict():
    old = make("old", "1", span=(0, 10), author="park")
    new = make("new", "2", span=(0, 10), author="jung", seen=("old",))
    assert relation(new, old) == REL_CONFLICT
    assert required_voters(new, [old, new]) == {"jung", "park"}


def test_d6_one_sentence_with_two_conditions_is_not_recitation():
    first = make("a", "0.8", span=(0, 30), conditions={"data": "v1"})
    second = make("b", "0.9", span=(0, 30), conditions={"data": "v2"})
    assert relation(second, first) == CONDITION_DIFFERS


def test_d6_narrow_decision_does_not_replace_wide_decision():
    wide = make("wide", "x", DECISION, conditions={"n": "*"})
    narrow = make("narrow", "y", DECISION, conditions={"n": "12"}, seen=("wide",))
    votes = yes("wide", "a") + yes("narrow", "a")
    assert claim_states([wide, narrow], votes) == {"wide": APPROVED, "narrow": APPROVED}
    assert evaluate("t", [wide, narrow], votes, {"n": "12"}).status == CONFLICT
    other = evaluate("t", [wide, narrow], votes, {"n": "40"})
    assert (other.status, other.groups[0].entries[0].claim.id) == (ANSWERED, "wide")


def test_d6_wide_decision_replaces_narrow_decision():
    narrow = make("narrow", "y", DECISION, conditions={"n": "12"})
    wide = make("wide", "x", DECISION, conditions={"n": "*"}, seen=("narrow",))
    states = claim_states([narrow, wide], yes("narrow", "a") + yes("wide", "a"))
    assert states["narrow"] == SUPERSEDED


def test_d6_wide_decision_replaces_wide_decision():
    old = make("old", "x", DECISION, conditions={"n": "*"})
    new = make("new", "y", DECISION, conditions={"n": "*"}, seen=("old",))
    assert claim_states([old, new], yes("old", "a") + yes("new", "a"))["old"] == SUPERSEDED


def test_d6_rejected_old_claim_needs_no_approval():
    old = make("old", "1", author="park")
    new = make("new", "2", author="jung", seen=("old",))
    votes = [Vote("old", "park", REJECT, "1")] + yes("new", "jung")
    for claims in ([old, new], [new, old]):
        assert claim_states(claims, votes) == {"old": REJECTED, "new": APPROVED}


def test_d6_replaced_old_decision_needs_no_approval():
    first = make("first", "1", DECISION, author="park")
    second = make("second", "2", DECISION, author="kim", seen=("first",))
    third = make("third", "3", DECISION, author="jung", seen=("first", "second"))
    votes = yes("first", "park") + yes("second", "kim", "park") + yes("third", "jung", "kim")
    for claims in ([first, second, third], [third, first, second]):
        states = claim_states(claims, votes)
        assert (states["first"], states["second"], states["third"]) == (SUPERSEDED, SUPERSEDED, APPROVED)


def test_d6_old_author_is_needed_until_old_claim_is_replaced():
    first = make("first", "1", DECISION, author="park")
    second = make("second", "2", DECISION, author="kim", seen=("first",))
    third = make("third", "3", DECISION, author="jung", seen=("first", "second"))
    votes = yes("first", "park") + yes("second", "kim") + yes("third", "jung", "kim")
    assert claim_states([first, second, third], votes)["third"] == CANDIDATE


def test_d6_condition_differs_and_support_add_no_approval():
    old = make("old", "1", author="park", conditions={"n": "12"})
    other = make("other", "2", author="jung", conditions={"n": "40"}, seen=("old",))
    same = make("same", "1", author="kim", conditions={"n": "12"}, seen=("old",))
    assert required_voters(other, [old, other]) == {"jung"}
    assert required_voters(same, [old, same]) == {"kim"}


def test_d6_returning_to_an_old_value_keeps_the_chain():
    first = make("first", "1", DECISION)
    second = make("second", "2", DECISION, seen=("first",))
    third = make("third", "1", DECISION, seen=("first", "second"))
    votes = yes("first", "a") + yes("second", "a") + yes("third", "a")
    for claims in ([first, second, third], [third, second, first]):
        states = claim_states(claims, votes)
        assert (states["first"], states["second"], states["third"]) == (SUPERSEDED, SUPERSEDED, APPROVED)


# D7

def test_d7_last_vote_wins():
    claim = make("c")
    votes = [Vote("c", "a", APPROVE, "2"), Vote("c", "a", REJECT, "1")]
    assert claim_states([claim], votes)["c"] == APPROVED
    assert approvers(claim, votes) == ["a"]


def test_d7_no_vote_stays_candidate():
    assert claim_states([make("c")], [])["c"] == CANDIDATE


# D8 ③ 거르기와 ④ 상태

def test_d8_status_no_evidence():
    assert evaluate("t", [], []).status == NO_EVIDENCE
    assert evaluate("other", [make("c")], yes("c", "a")).status == NO_EVIDENCE


def test_d8_status_conflict_mixes_approved_and_candidate():
    claims = [make("c1", "1"), make("c2", "2", author="b", seen=("c1",))]
    result = evaluate("t", claims, yes("c1", "a"))
    assert result.status == CONFLICT
    assert {entry.claim.id: entry.state for entry in result.groups[0].entries} == {"c1": APPROVED, "c2": CANDIDATE}


def test_d8_status_answered_lists_approver_and_independent_count():
    claims = [make("c1", "1", span=(0, 10)), make("c2", "1", span=(5, 15)), make("c3", "1", span=(50, 60))]
    result = evaluate("t", claims, yes("c1", "a") + yes("c2", "a") + yes("c3", "a"))
    assert result.status == ANSWERED
    assert result.groups[0].independent == 2
    assert result.groups[0].entries[0].approvers == ["a"]


def test_d8_status_only_unapproved():
    assert evaluate("t", [make("c")], []).status == ONLY_UNAPPROVED


def test_d8_candidate_does_not_count_as_independent_evidence():
    claims = [make("c1", "1"), make("c2", "1")]
    assert evaluate("t", claims, yes("c1", "a")).groups[0].independent == 1


def test_d8_each_group_has_its_own_status():
    claims = [make("c1", "1", conditions={"n": "12"}), make("c2", "2", conditions={"n": "40"}),
              make("c3", "3", conditions={"n": "40"}, seen=("c2",)), make("c4", "4", conditions={"n": "7"})]
    result = evaluate("t", claims, yes("c1", "a"))
    assert result.status == BY_CONDITION
    assert {group.conditions["n"]: group.status for group in result.groups} == {
        "12": ANSWERED, "40": CONFLICT, "7": ONLY_UNAPPROVED}


def test_d8_rejected_claim_is_removed():
    votes = [Vote("c", "a", REJECT, "1")]
    assert evaluate("t", [make("c")], votes).status == NO_EVIDENCE


def test_d8_current_question_drops_old_decision_with_a_note():
    old = make("old", "1", DECISION)
    new = make("new", "2", DECISION, seen=("old",))
    result = evaluate("t", [old, new], yes("old", "a") + yes("new", "a"))
    assert result.status == ANSWERED
    assert [entry.claim.id for entry in result.groups[0].entries] == ["new"]
    assert [claim.id for claim in result.previous] == ["old"]


def test_d8_history_question_marks_old_decision_without_conflict():
    old = make("old", "1", DECISION)
    new = make("new", "2", DECISION, seen=("old",))
    result = evaluate("t", [old, new], yes("old", "a") + yes("new", "a"), time=HISTORY)
    assert result.status == ANSWERED
    assert {entry.claim.id: entry.previous for entry in result.groups[0].entries} == {"old": True, "new": False}


def test_d8_observations_and_decisions_do_not_conflict_with_each_other():
    claims = [make("o", "0.842"), make("d", "xgboost", DECISION)]
    assert evaluate("t", claims, yes("o", "a") + yes("d", "a")).status == ANSWERED


def test_d8_two_unverified_values_conflict_when_nothing_matches():
    claims = [make("k", "0", conditions={"n": "40"}), make("c1", "1"), make("c2", "2", seen=("c1",))]
    assert evaluate("t", claims, yes("c1", "a") + yes("c2", "a"), {"n": "12"}).status == CONFLICT


def test_d8_matching_claim_decides_status_over_unverified():
    claims = [make("c1", "1", conditions={"n": "12"}), make("c2", "2")]
    result = evaluate("t", claims, yes("c1", "a") + yes("c2", "a"), {"n": "12"})
    assert result.status == ANSWERED
    assert {entry.claim.id: entry.unverified for entry in result.groups[0].entries} == {"c1": False, "c2": True}


def test_d8_source_check_reports_latest_version():
    kept = make("c1", "1", quote="AUC 0.84")
    gone = make("c2", "1", quote="AUC 0.90")
    result = evaluate("t", [kept, gone], yes("c1", "a") + yes("c2", "a"), latest={"doc": "AUC 0.84 측정"})
    assert {entry.claim.id: entry.source for entry in result.groups[0].entries} == {
        "c1": SOURCE_CONFIRMED, "c2": SOURCE_MISSING}


def test_d8_aliases_merge_topic_and_key():
    claims = apply_aliases([make("c1", "1", topic="최고모델", conditions={"data": "v1"})],
                           {"최고모델": "best_model"}, {"data": "dataset"})
    result = evaluate("best_model", claims, yes("c1", "a"), {"dataset": "v1"})
    assert result.status == ANSWERED


# D12 앞뒤 순서

def test_d12_seen_record_comes_first():
    first, second = make("first"), make("second", seen=("first",))
    assert is_earlier(first, second)
    assert not is_earlier(second, first)
    assert not is_concurrent(first, second)


def test_d12_earlier_claim_needs_no_approval_from_later_author():
    first = make("first", "1", author="park")
    second = make("second", "2", author="jung", seen=("first",))
    assert required_voters(first, [first, second]) == {"park"}


def test_d12_concurrent_conflict_needs_both_authors_on_both():
    a = make("a1", "1", DECISION, author="park")
    b = make("b1", "2", DECISION, author="jung")
    assert is_concurrent(a, b)
    assert required_voters(a, [a, b]) == {"park", "jung"}
    assert required_voters(b, [a, b]) == {"park", "jung"}


def test_d12_concurrent_rejection_resolves_to_the_other_claim():
    a = make("a1", "1", DECISION, author="park")
    b = make("b1", "2", DECISION, author="jung")
    votes = yes("a1", "park", "jung") + yes("b1", "jung") + [Vote("b1", "park", REJECT, "2")]
    states = claim_states([a, b], votes)
    assert (states["a1"], states["b1"]) == (APPROVED, REJECTED)


def test_d12_concurrent_mutual_approval_stays_in_conflict():
    a = make("a1", "1", DECISION, author="park")
    b = make("b1", "2", DECISION, author="jung")
    votes = yes("a1", "park", "jung") + yes("b1", "park", "jung")
    assert claim_states([a, b], votes) == {"a1": APPROVED, "b1": APPROVED}
    assert evaluate("t", [a, b], votes).status == CONFLICT


def test_d12_mutual_rejection_rejects_both():
    a = make("a1", "1", DECISION, author="park")
    b = make("b1", "2", DECISION, author="jung")
    votes = yes("a1", "park") + yes("b1", "jung") + [Vote("a1", "jung", REJECT, "2"), Vote("b1", "park", REJECT, "2")]
    assert claim_states([a, b], votes) == {"a1": REJECTED, "b1": REJECTED}


def test_independent_count_follows_chains():
    claims = [make("a", span=(0, 10)), make("c", span=(20, 30)), make("b", span=(5, 25))]
    assert independent_count(claims) == 1
    assert independent_count([]) == 0
