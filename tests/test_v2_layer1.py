"""구조화 재시도, 답 검사 규칙, 1층 데이터 도우미 테스트. 서버 없이 가짜 LLM으로 돈다."""
import httpx
import pytest

from eval.layer1 import change_number, parse_indices, split_of
from harness_v2.check import AskContext, check_answer, checklist
from harness_v2.llm import LLMError, ServerLLM
from harness_v2.structure import extract_claims, normalize_name

NOTE = "회의 기록입니다. " * 30 + "v1 데이터에서 XGBoost AUC는 0.842였다."
CLAIM = {"kind": "observation", "topic": "Best Model", "value": "XGBoost", "conditions": [],
         "statement": "XGBoost가 가장 좋다.", "quote": "XGBoost AUC는 0.900였다."}


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete_json(self, *, prompt_version, system, user, schema):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_retry_fixes_bad_quote_and_sends_nearest_span():
    llm = FakeLLM([{"claims": [CLAIM]}, {"quote": "XGBoost AUC는 0.842였다."}])
    claim = extract_claims(llm, NOTE).claims[0]
    assert claim.ok and not claim.first_try_ok and claim.retries == 1
    assert "0.842" in llm.prompts[1]
    assert claim.data["topic"] == "best_model"


def test_claim_dropped_after_two_failed_retries():
    llm = FakeLLM([{"claims": [CLAIM]}, {"quote": "없는 문장"}, {"quote": "또 없는 문장"}])
    result = extract_claims(llm, NOTE)
    assert result.claims[0].retries == 2
    assert result.stored == []


def test_short_note_is_auto_quoted():
    result = extract_claims(FakeLLM([{"claims": [CLAIM]}]), "XGBoost가 좋았다.")
    assert result.stored[0].data["quote"] == "XGBoost가 좋았다."


def test_server_error_is_reported():
    assert extract_claims(FakeLLM([LLMError("down")]), NOTE).error == "down"


def test_normalize_name():
    assert normalize_name(" Best-Model ") == normalize_name("best_model") == "best_model"


def passing(ctx):
    return {"results": [{"id": item, "passed": True, "sentence": "", "fix": ""} for item in checklist(ctx)]}


def test_check_passes_when_all_items_pass():
    ctx = AskContext("q", "conflict", {1: "a", 2: "b"})
    assert check_answer(FakeLLM([passing(ctx)]), ctx, "a [1], b [2]")["pass"]


def test_unknown_reference_fails_by_rule():
    ctx = AskContext("q", "answered", {1: "a"})
    verdict = check_answer(FakeLLM([passing(ctx)]), ctx, "a [3]")
    assert not verdict["pass"] and verdict["problems"][0]["type"] == "bad_ref"


def test_missing_checklist_item_does_not_pass():
    ctx = AskContext("q", "no_evidence")
    assert not check_answer(FakeLLM([{"results": []}]), ctx, "없음")["pass"]


def test_status_adds_its_checklist_item():
    assert "both_sides" in checklist(AskContext("q", "conflict"))
    assert "both_sides" not in checklist(AskContext("q", "answered"))


def test_server_error_is_not_a_pass():
    ctx = AskContext("q", "answered", {1: "a"})
    verdict = check_answer(FakeLLM([LLMError("down")]), ctx, "a [1]")
    assert not verdict["pass"] and verdict["error"] == "down"


def test_parse_indices():
    assert parse_indices("1, 4-6, 8") == {1, 4, 5, 6, 8}


def test_change_number():
    assert change_number("65%") == "68%"
    assert change_number("Confluence") is None


def test_split_is_stable():
    assert split_of("abc") == split_of("abc")
    assert {split_of(str(n)) for n in range(50)} == {"dev", "test"}


class FakeResponse:
    def __init__(self, message):
        self.message = message

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": self.message}]}


def post_returning(message, sent):
    def post(url, json, timeout):
        sent.append(json)
        return FakeResponse(message)
    return post


def ask(llm):
    return llm.complete_json(prompt_version="v", system="s", user="u", schema={})


def test_thinking_flag_is_sent_and_reasoning_counted(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(httpx, "post", post_returning({"content": "{}", "reasoning_content": "because"}, sent))
    llm = ServerLLM(log_path=tmp_path / "calls.jsonl", thinking=True)
    assert ask(llm) == {}
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert sent[0]["max_tokens"] == 8192
    assert llm.stats["with_reasoning"] == 1


def test_empty_content_is_an_error_and_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", post_returning({"content": None}, []))
    llm = ServerLLM(log_path=tmp_path / "calls.jsonl", thinking=True)
    with pytest.raises(LLMError):
        ask(llm)
    assert not (tmp_path / "calls.jsonl").exists()


def test_thinking_results_do_not_share_cache(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(httpx, "post", post_returning({"content": "{}"}, sent))
    path = tmp_path / "calls.jsonl"
    ask(ServerLLM(log_path=path, thinking=False))
    ask(ServerLLM(log_path=path, thinking=True))
    assert len(sent) == 2


def test_requests_alternate_between_servers(monkeypatch, tmp_path):
    urls = []

    def post(url, json, timeout):
        urls.append(url)
        return FakeResponse({"content": "{}"})

    monkeypatch.setattr(httpx, "post", post)
    llm = ServerLLM(base_url="http://a/v1,http://b/v1", log_path=tmp_path / "calls.jsonl")
    for user in ("1", "2", "3"):
        llm.complete_json(prompt_version="v", system="s", user=user, schema={})
    assert urls == ["http://a/v1/chat/completions", "http://b/v1/chat/completions", "http://a/v1/chat/completions"]


def test_conflict_uses_its_own_support_item():
    conflict = checklist(AskContext("q", "conflict"))["no_unsupported"]
    assert conflict != checklist(AskContext("q", "answered"))["no_unsupported"]
