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


def test_pii_masked_before_sharing():
    h = load()
    r14, r15 = h.store.records["R14"], h.store.records["R15"]
    assert "010-2345-6789" not in r14.text and "minsu.kim@example.com" not in r14.text
    assert "sk-live-" not in r15.text
    assert r14.citation_valid  # 인용 검증은 가리기 전 원문 기준
    assert set(r14.pii_types) == {"email", "phone"} and r15.pii_types == ["api_key"]


def test_pii_guard_ignores_normal_numbers():
    from harness.pii import PIIGuard
    text, kinds = PIIGuard().mask("XGBoost AUC 0.842, learning_rate 0.05, 피처 12개")
    assert kinds == [] and "0.842" in text


def test_graphiti_adapter_maps_episodes_to_records():
    """Neo4j 없이 가짜 Graphiti 객체로 어댑터의 매핑 로직만 확인한다."""
    import pytest
    pytest.importorskip("graphiti_core")
    from types import SimpleNamespace as NS
    from baselines.graphiti_baseline import GraphitiBaseline

    class FakeGraphiti:
        def __init__(self):
            self.n = 0
        async def build_indices_and_constraints(self): pass
        async def add_episode(self, **kw):
            self.n += 1
            return NS(episode=NS(uuid=f"ep{self.n}"), edges=[])
        async def search(self, query, group_ids=None, num_results=10):
            return [NS(fact="XGBoost가 가장 좋다", episodes=["ep1", "ep2"], invalid_at=None, expired_at=None),
                    NS(fact="LightGBM이 더 좋다", episodes=["ep3"], invalid_at="2026-09-29", expired_at=None)]
        async def close(self): pass

    recs = [Record.from_dict(r) for r in json.loads((DATA / "records.json").read_text(encoding="utf-8"))][:3]
    gb = GraphitiBaseline(DATA / "sources", graphiti=FakeGraphiti(), group_id="t")
    gb.ingest(recs)
    resp = gb.ask(Query("x", "모델?"))
    assert resp.supporting_ids == ["R01", "R02"]   # 무효 처리된 사실은 제외
    assert resp.team_fact_ids == resp.supporting_ids
    gb.close()


def test_llm_mode_plumbing_without_api(monkeypatch):
    """API 키 없이 가짜 LLM으로 공정 비교 모드의 배선만 확인한다."""
    import pytest
    pytest.importorskip("pydantic")
    from harness import llm
    from baselines.full_context_llm import FullContextLLM
    from baselines.retrieval_only import RetrievalOnly

    seen_prompts = []

    def fake_structure(text, source, known):
        seen_prompts.append(text + source)
        return "best_model", "XGBoost", {"n_features": 12, "dataset": "v1"}

    def fake_answer(question, context):
        seen_prompts.append("\n".join(context))
        return llm.LLMAnswer(status="answered", supporting_ids=["R01"], team_fact_ids=["R01"],
                             independent_evidence=1, answer="XGBoost")

    monkeypatch.setattr(llm, "structure_record", fake_structure)
    monkeypatch.setattr(llm, "parse_query", lambda q, topics: ("best_model", {"n_features": 12, "dataset": "v1"}))
    monkeypatch.setattr(llm, "answer", fake_answer)
    monkeypatch.setattr(llm, "detect_pii_spans", lambda text: ["김민수"] if "김민수" in text else [])

    raw = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    h = Harness(DATA / "sources", structure="llm", answerer="llm")
    h.ingest([Record.from_dict(r) for r in raw])
    resp = h.ask(Query("x", "피처 12개 v1 모델?"))
    assert resp.status == "answered" and any("[하네스 판정]" in c for c in resp.exposed)
    # 구조화·답변 프롬프트로 나간 텍스트에 민감 정보가 없어야 한다(가린 사본만 외부 LLM으로)
    assert not any(s in p for p in seen_prompts for s in ("010-2345-6789", "minsu.kim@example.com", "김민수"))

    for system in (FullContextLLM(DATA / "sources"), RetrievalOnly(DATA / "sources", answerer="llm")):
        system.ingest([Record.from_dict(r) for r in raw])
        resp = system.ask(Query("x", "피처 12개, 데이터 v1에서 이탈 예측 모델은 뭐가 좋아?"))
        assert any(c.startswith("<source") for c in resp.exposed)  # 원문도 같이 넘어간다
        assert not any("conditions" in c or "n_features" in c for c in resp.exposed[:1])  # 정답 조건 필드는 안 넘김
