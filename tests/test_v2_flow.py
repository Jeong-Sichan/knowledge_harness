"""글 올리기에서 답 검사 입력까지 잇는 테스트. 서버 없이 LLM 응답을 정해 둔다."""
import json

from harness_v2.approval import APPROVED, CANDIDATE, SUPERSEDED, claim_states
from harness_v2.ask import ANSWERED, BY_CONDITION, CONFLICT, NO_EVIDENCE, ONLY_UNAPPROVED
from harness_v2.llm import LLMError
from harness_v2.model import APPROVE, DECISION, OBSERVATION, Claim, Evidence, Vote
from harness_v2.relations import CONFLICT as REL_CONFLICT
from harness_v2.relations import NEEDS_COMPARISON
from harness_v2.respond import MAX_EVIDENCE, ask_context, respond
from harness_v2.store import FileStore, Store
from harness_v2.submit import shown_names, split_note, submit_note

PADDING = " 자세한 실험 기록은 아래와 같다." * 20


class ScriptedLLM:
    """글에 든 표시 문장으로 응답을 고른다. 받은 입력을 기록한다."""
    model = "test-model"

    def __init__(self, notes=None, questions=None):
        self.notes = notes or {}
        self.questions = questions or {}
        self.calls = []

    def complete_json(self, *, prompt_version, system, user, schema):
        self.calls.append((prompt_version, user))
        table = self.questions if prompt_version.startswith("interpret") else self.notes
        for marker, reply in table.items():
            if marker in user:
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise AssertionError(f"정하지 않은 입력: {user[:80]}")


def fact(kind, topic, value, quote, conditions=None, statement=None):
    pairs = [{"key": key, "value": item} for key, item in (conditions or {}).items()]
    return {"kind": kind, "topic": topic, "value": value, "conditions": pairs,
            "statement": statement or f"{topic} is {value}", "quote": quote}


def question(topics, conditions=None, time="current"):
    pairs = [{"key": key, "value": item} for key, item in (conditions or {}).items()]
    return {"topics": topics, "conditions": pairs, "time": time}


def approve(store, claim_id, voter, at="1"):
    store.add_vote(Vote(claim_id, voter, APPROVE, at))


def note_with(store, llm, text, author="a", **rest):
    return submit_note(llm, store, text, author, **rest)


def simple_store(*facts):
    """주장 하나씩 든 글을 올린 저장소를 돌려준다."""
    store, notes = Store(), {}
    for number, item in enumerate(facts):
        marker = f"글{number}번"
        text = f"{marker} {item['quote']}{PADDING}"
        notes[marker] = {"claims": [item]}
        note_with(store, ScriptedLLM(notes), text, doc=f"doc{number}")
    return store


# 저장소

def test_source_same_content_is_not_saved_twice():
    store = Store()
    assert store.add_source("n", "글", "a")[1]
    assert not store.add_source("n", "글", "a")[1]
    assert len(store.sources) == 1


def test_source_new_content_gets_next_revision():
    store = Store()
    store.add_source("n", "글", "a")
    source, _ = store.add_source("n", "고친 글", "a")
    assert source.rev == 2
    assert store.latest_texts() == {"n": "고친 글"}


def test_claim_id_is_a_content_hash():
    store = Store()
    claim = Claim("", OBSERVATION, "t", "1", "a")
    assert store.add_claim(claim).id == store.add_claim(claim).id
    assert store.add_claim(Claim("", OBSERVATION, "t", "2", "a")).id != store.add_claim(claim).id


def test_file_store_reads_back_everything(tmp_path):
    store = FileStore(tmp_path)
    store.add_source("n", "글", "a")
    evidence = (Evidence("n", 0, 1, "글"),)
    claim = store.add_claim(Claim("", DECISION, "t", "1", "a", {"k": "v"}, evidence, seen=("x",), statement="s"))
    approve(store, claim.id, "a")
    store.add_alias("topic", "옛이름", "t", "a")

    again = FileStore(tmp_path)
    assert again.claims[claim.id] == claim
    assert again.votes == store.votes
    assert again.latest_texts() == {"n": "글"}
    assert again.aliases["topic"] == {"옛이름": "t"}
    assert sorted(path.name for path in tmp_path.iterdir()) == ["aliases", "claims", "sources", "votes"]


# 글 올리기

def test_split_note_keeps_offsets_and_cuts_at_paragraphs():
    text = "가" * 50 + "\n\n" + "나" * 50 + "\n\n" + "다" * 50
    chunks = split_note(text, limit=60)
    assert "".join(chunk for _, chunk in chunks) == text
    assert all(text[start:start + len(chunk)] == chunk for start, chunk in chunks)
    assert chunks[1][1].startswith("나")


def test_split_note_without_line_breaks_cuts_at_limit():
    assert [len(chunk) for _, chunk in split_note("가" * 25, limit=10)] == [10, 10, 5]


def test_shown_names_limits_long_lists_by_word_overlap():
    names = [f"topic_{number}" for number in range(100)]
    assert shown_names("아무 글", names) == names
    names.append("fetch_output")
    shown = shown_names("Git fetch output style", names)
    assert len(shown) == 30
    assert shown[0] == "fetch_output"
    assert len(shown_names("Git fetch output style", names, 100)) == 100


def test_question_sees_more_topics_than_a_note():
    store = Store()
    for number in range(150):
        store.add_claim(Claim("", OBSERVATION, f"topic_{number:03}", "1", "a", {}, (Evidence("d", 0, 1, "x"),)))
    llm = ScriptedLLM(questions={"질문": question([])})
    respond(llm, store, "질문")
    listed = llm.calls[0][1].splitlines()[0]
    assert listed.count("topic_") == 100


def test_submit_shows_existing_condition_keys_to_the_model():
    store = simple_store(fact(OBSERVATION, "t", "1", "첫 문장", {"n_features": "12"}))
    llm = ScriptedLLM({"둘째": {"claims": []}})
    note_with(store, llm, f"둘째 글{PADDING}")
    assert "Existing condition keys: n_features" in llm.calls[0][1]


def test_submit_turns_extraction_into_claims():
    quote = "v1 결측치는 중앙값으로 간다"
    text = f"머리말. {quote}.{PADDING}"
    llm = ScriptedLLM({"머리말": {"claims": [fact(DECISION, "Missing Value", "median", quote, {"Data Set": "v1"})]}})
    store = Store()
    result = note_with(store, llm, text, "박재원", doc="exp_007")
    claim = result.claims[0]
    assert (claim.topic, claim.conditions, claim.author) == ("missing_value", {"data_set": "v1"}, "박재원")
    item = claim.evidence[0]
    assert text[item.start:item.end] == quote
    assert claim.written_by["model"] == "test-model"


def test_submit_shifts_quote_position_in_later_chunks():
    first, second = "앞" * 5990 + "\n\n", "둘째 조각의 문장이다."
    text = first + second + PADDING
    llm = ScriptedLLM({"둘째": {"claims": [fact(OBSERVATION, "t", "1", second)]}, "앞": {"claims": []}})
    claim = note_with(Store(), llm, text).claims[0]
    assert text[claim.evidence[0].start:claim.evidence[0].end] == second


def test_submit_records_seen_only_for_the_same_topic():
    store = simple_store(fact(OBSERVATION, "t", "1", "첫 문장"), fact(OBSERVATION, "other", "2", "둘째 문장"))
    first = next(claim for claim in store.claims.values() if claim.topic == "t")
    third = fact(OBSERVATION, "t", "3", "셋째 문장")
    result = note_with(store, ScriptedLLM({"셋째": {"claims": [third]}}), f"셋째 문장{PADDING}", "b")
    assert result.claims[0].seen == (first.id,)
    assert result.relations == [(result.claims[0].id, first.id, REL_CONFLICT)]


def test_submit_same_note_again_does_not_call_the_model():
    llm = ScriptedLLM({"문장": {"claims": []}})
    store = Store()
    text = f"문장{PADDING}"
    note_with(store, llm, text)
    assert not note_with(store, llm, text).is_new
    assert len(llm.calls) == 1


def test_submit_masks_sensitive_text_before_saving():
    llm = ScriptedLLM({"연락처": {"claims": []}})
    store = Store()
    result = note_with(store, llm, f"연락처 010-1234-5678{PADDING}")
    assert result.masked == ["phone"]
    assert "1234" not in result.source.text
    assert "1234" not in llm.calls[0][1]


def test_submit_keeps_source_when_model_is_down():
    llm = ScriptedLLM({"문장": LLMError("down")})
    store = Store()
    result = note_with(store, llm, f"문장{PADDING}")
    assert result.errors == ["down"]
    assert len(store.sources) == 1 and not store.claims


# ask 응답

def test_ask_answered_lists_approver_and_source():
    store = simple_store(fact(DECISION, "t", "median", "중앙값으로 간다"))
    claim = next(iter(store.claims.values()))
    approve(store, claim.id, "a")
    response = respond(ScriptedLLM(questions={"질문": question(["t"])}), store, "질문")
    assert response["status"] == ANSWERED
    assert response["evidence"][0]["ref"] == 1
    assert response["evidence"][0]["quote"] == "중앙값으로 간다"
    assert response["safe_answer"] == "median [1] (승인: a), 독립 근거 1개"
    assert response["understood_as"] == {"topics": ["t"], "conditions": {}, "time": "current"}


def test_ask_candidate_is_not_stated_as_fact():
    store = simple_store(fact(DECISION, "t", "median", "중앙값으로 간다"))
    response = respond(ScriptedLLM(questions={"질문": question(["t"])}), store, "질문")
    assert response["status"] == ONLY_UNAPPROVED
    assert response["safe_answer"].startswith("아직 승인되지 않은 기록에 따르면")
    assert any("not approved" in rule for rule in response["answer_rules"])


def test_ask_unknown_topic_is_no_evidence():
    store = simple_store(fact(DECISION, "t", "median", "중앙값으로 간다"))
    response = respond(ScriptedLLM(questions={"질문": question(["없는_주제"])}), store, "질문")
    assert response["status"] == NO_EVIDENCE
    assert response["understood_as"]["topics"] == []
    assert response["safe_answer"] == "이 질문에 답할 근거가 없습니다."


def test_ask_model_down_gives_no_guess():
    store = simple_store(fact(DECISION, "t", "median", "중앙값으로 간다"))
    response = respond(ScriptedLLM(questions={"질문": LLMError("down")}), store, "질문")
    assert response["status"] == "error"
    assert not response["evidence"]


def test_ask_groups_conditions_with_their_own_refs():
    store = simple_store(fact(OBSERVATION, "t", "1", "12개 결과", {"n": "12"}), fact(OBSERVATION, "t", "2", "40개 결과", {"n": "40"}))
    for claim in store.claims.values():
        approve(store, claim.id, "a")
    response = respond(ScriptedLLM(questions={"질문": question(["t"])}), store, "질문")
    assert response["status"] == BY_CONDITION
    assert [group["refs"] for group in response["groups"]] == [[1], [2]]
    assert response["safe_answer"].splitlines()[0].startswith("n=12: 1 [1]")


def test_ask_bundles_recitation_into_one_ref():
    store, text = Store(), f"같은 문장이다{PADDING}"
    source, _ = store.add_source("doc", text, "a")
    for author in ("a", "b"):
        claim = store.add_claim(Claim("", OBSERVATION, "t", "1", author, {}, (Evidence("doc", 0, 6, "같은 문장이다"),)))
        approve(store, claim.id, author)
    response = respond(ScriptedLLM(questions={"질문": question(["t"])}), store, "질문")
    assert len(response["evidence"]) == 1
    assert response["evidence"][0]["recited"] == 1
    assert response["evidence"][0]["approved_by"] == ["a", "b"]
    assert response["groups"][0]["independent"] == 1


def test_ask_evidence_limit_keeps_both_sides_of_a_conflict():
    facts = [fact(OBSERVATION, "t", "1", f"같은 값 문장 {number}") for number in range(15)]
    store = simple_store(*facts, fact(OBSERVATION, "t", "2", "다른 값 문장"))
    response = respond(ScriptedLLM(questions={"질문": question(["t"])}), store, "질문")
    assert len(response["evidence"]) == MAX_EVIDENCE
    assert {item["value"] for item in response["evidence"]} == {"1", "2"}
    assert "근거 6개는 한도 때문에 생략함" in response["notes"]


def test_ask_two_topics_answer_together():
    store = simple_store(fact(OBSERVATION, "p", "1", "첫 문장"), fact(OBSERVATION, "q", "2", "둘째 문장"))
    response = respond(ScriptedLLM(questions={"질문": question(["p", "q", "없음"])}), store, "질문")
    assert response["status"] == BY_CONDITION
    assert [group["topic"] for group in response["groups"]] == ["p", "q"]


def test_ask_uses_aliases():
    store = simple_store(fact(OBSERVATION, "best_model", "xgb", "최고 모델은 xgb"))
    store.add_alias("topic", "최고모델", "best_model", "a")
    response = respond(ScriptedLLM(questions={"질문": question(["최고모델"])}), store, "질문")
    assert response["understood_as"]["topics"] == ["best_model"]


def test_ask_reports_quote_gone_from_latest_version():
    store = simple_store(fact(OBSERVATION, "t", "1", "지워질 문장"))
    store.add_source("doc0", "완전히 다른 글", "a")
    response = respond(ScriptedLLM(questions={"질문": question(["t"])}), store, "질문")
    assert "[1] 최신 원문에서 사라짐, 재확인 필요" in response["notes"]


def test_response_is_json_serializable():
    store = simple_store(fact(DECISION, "t", "median", "중앙값으로 간다", {"n": "12"}))
    json.dumps(respond(ScriptedLLM(questions={"질문": question(["t"])}), store, "질문"), ensure_ascii=False)


def test_ask_context_uses_strictest_status_of_groups():
    store = simple_store(fact(OBSERVATION, "t", "1", "12개 결과", {"n": "12"}), fact(OBSERVATION, "t", "2", "40개 결과", {"n": "40"}),
                         fact(OBSERVATION, "t", "3", "40개 다른 결과", {"n": "40"}))
    response = respond(ScriptedLLM(questions={"질문": question(["t"])}), store, "질문")
    context = ask_context(response)
    assert context.status == CONFLICT
    assert set(context.evidence) == {1, 2, 3}


# D13 실행 시나리오 1~6

def test_design_scenario_from_note_to_decision_change():
    store = Store()
    note1 = "v1에서 중앙값이 KNN보다 AUC 0.003 높아서 중앙값으로 가기로"
    note2 = "KNN k=5가 0.006 더 높아, KNN으로 바꾸자"
    notes = {
        "중앙값으로 가기로": {"claims": [
            fact(OBSERVATION, "imputer_auc", "median +0.003", note1, {"dataset": "v1"}),
            fact(DECISION, "missing_value", "median", note1, {"dataset": "v1"})]},
        "KNN으로 바꾸자": {"claims": [
            fact(OBSERVATION, "imputer_auc", "knn +0.006", note2, {"dataset": "v1", "k": "5"}),
            fact(DECISION, "missing_value", "knn", note2, {"dataset": "v1"})]},
    }
    asked = {"어떻게 하기로": question(["missing_value"], {"dataset": "v1"}),
             "예전엔": question(["missing_value"], {"dataset": "v1"}, "history")}
    llm = ScriptedLLM(notes, asked)

    # 1. 박재원이 올리고 본인 승인
    first = note_with(store, llm, note1, "박재원", doc="n1")
    assert [claim.kind for claim in first.claims] == [OBSERVATION, DECISION]
    old_decision = first.claims[1]
    for claim in first.claims:
        approve(store, claim.id, "박재원", "1")

    # 2. 정시찬의 질문에 답할 수 있음
    response = respond(llm, store, "v1 결측치 처리 어떻게 하기로 했어?")
    assert response["status"] == ANSWERED
    assert response["safe_answer"] == "median [1] (승인: 박재원), 독립 근거 1개"

    # 3. 정시찬의 새 글: 결정은 충돌, 관측은 비교 필요
    second = note_with(store, llm, note2, "정시찬", doc="n2")
    new_decision = second.claims[1]
    kinds = {(new, old): kind for new, old, kind in second.relations}
    assert kinds[(new_decision.id, old_decision.id)] == REL_CONFLICT
    assert kinds[(second.claims[0].id, first.claims[0].id)] == NEEDS_COMPARISON
    for claim in second.claims:
        approve(store, claim.id, "정시찬", "2")
    assert claim_states(store.all_claims(), store.votes)[new_decision.id] == CANDIDATE

    # 4. 박재원 승인 전에는 충돌
    response = respond(llm, store, "v1 결측치 처리 어떻게 하기로 했어?")
    assert response["status"] == CONFLICT
    assert ask_context(response).status == CONFLICT
    assert {item["value"] for item in response["evidence"]} == {"median", "knn"}

    # 5. 박재원이 승인하면 KNN이 현재 결정, 중앙값은 이전 결정
    approve(store, new_decision.id, "박재원", "3")
    states = claim_states(store.all_claims(), store.votes)
    assert (states[old_decision.id], states[new_decision.id]) == (SUPERSEDED, APPROVED)

    # 6. 이후 질문과 이력 질문
    response = respond(llm, store, "v1 결측치 처리 어떻게 하기로 했어?")
    assert response["status"] == ANSWERED
    assert response["safe_answer"].startswith("knn [1] (승인: 박재원, 정시찬), 독립 근거 1개")
    assert any(note.startswith("이전 결정: median") for note in response["notes"])
    assert ask_context(response).previous_decisions

    response = respond(llm, store, "예전엔?")
    assert response["status"] == ANSWERED
    assert {item["value"]: item["previous"] for item in response["evidence"]} == {"median": True, "knn": False}
