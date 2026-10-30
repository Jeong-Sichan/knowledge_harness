import json
from pathlib import Path

from harness import Harness, Query, Record
from harness.relation import CONDITION_DIFFERS, CONFLICT, NONE, RECITATION
from harness.schema import ANSWERED, CONFLICT as S_CONFLICT, NO_EVIDENCE, ONLY_UNAPPROVED

DATA = Path(__file__).resolve().parent.parent / "data"


def load():
    h = Harness(DATA / "sources")
    h.ingest([Record.from_dict(r) for r in json.loads((DATA / "records.json").read_text(encoding="utf-8"))])
    return h


def test_relations_follow_table():
    log = dict(load().store.log)
    assert log["R01"] == NONE
    assert log["R02"] == RECITATION         # 같은 원문·버전·구간
    assert log["R03"] == CONDITION_DIFFERS  # dataset v2
    assert log["R04"] == CONFLICT           # 같은 조건, 다른 주장


def test_conflict_keeps_both_and_requests_review():
    h = load()
    assert h.store.records["R01"].needs_review and h.store.records["R04"].needs_review


def test_verifier_rejects_changed_number():
    h = load()
    assert h.store.records["R07"].citation_valid
    assert not h.store.records["R08"].citation_valid  # 0.05 → 0.1


def test_condition_gap_is_reported():
    resp = load().ask(Query("x", "피처 40개", "best_model", {"n_features": 40, "dataset": "v1"}))
    assert resp.status == NO_EVIDENCE and resp.supporting_ids == []


def test_recitation_not_counted_as_independent():
    resp = load().ask(Query("x", "중요 피처", "top_feature", {"n_features": 12, "dataset": "v1"}))
    assert resp.status == ANSWERED and resp.independent_evidence == 1


def test_unapproved_is_not_team_fact():
    resp = load().ask(Query("x", "불균형", "imbalance_method", {"n_features": 12, "dataset": "v2"}))
    assert resp.status == ONLY_UNAPPROVED and resp.team_fact_ids == []


def test_answer_cache_invalidated_by_new_record():
    h = load()
    q = Query("x", "모델", "best_model", {"n_features": 12, "dataset": "v2"})
    h.ask(q); h.ask(q)
    assert h.stats["answer_cache_hits"] == 1
    new = Record.from_dict({"id": "R99", "created_at": "2026-10-10T00:00", "author": "정시찬", "author_type": "human",
                            "text": "v2에서도 XGBoost", "topic": "best_model", "value": "XGBoost",
                            "conditions": {"n_features": 12, "dataset": "v2"},
                            "evidence": [{"source": "exp_002", "rev": 1, "quote": "XGBoost AUC 0.846"}]})
    h.store.add(new)
    assert h.ask(q).status == S_CONFLICT
