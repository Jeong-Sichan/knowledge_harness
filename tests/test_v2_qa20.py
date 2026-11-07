"""QA20 실행기 테스트. 서버 없이 돈다."""
import json
from hashlib import sha256

from eval.qa20 import chains, citations, run_case, source_id, write_answer
from harness_v2.llm import LLMError

QUOTE = "default  style is full"
TEXT = f"fetch.output sets the {QUOTE} for printing ref updates, and this sentence pads the note beyond the automatic quote limit. " * 4


def record(location="loc1", owner="Git docs", text=TEXT):
    return {"owner": owner, "observed_at": "2025-03-14T00:00:00+00:00",
            "source": {"speaker": owner, "location": location, "text": text}}


def case(*records, question="Which style?"):
    asked = json.dumps({"as_of": "2025-03-15T00:00:00+00:00", "question": question})
    return {"id": "legacy-x", "events": [{"label": "import", "operation": "import_history", "records": list(records)},
                                         {"label": "qa-0", "operation": "ask", "question": asked}]}


class PacketLLM:
    """추출, 해석, 답 쓰기, 답 검사 응답을 정해 둔다."""
    model = "test-model"

    def __init__(self, drafts=("full [1]",), passes=(True,), value="full"):
        self.drafts = list(drafts)
        self.passes = list(passes)
        self.value = value
        self.prompts = []

    def complete_json(self, *, prompt_version, system, user, schema):
        self.prompts.append((prompt_version, user))
        if prompt_version.startswith("structure"):
            claim = {"kind": "observation", "topic": "fetch_output", "value": self.value, "conditions": [],
                     "statement": "Fetch output defaults to full.", "quote": QUOTE}
            return {"claims": [claim]}
        if prompt_version.startswith("interpret"):
            return {"topics": ["fetch_output"], "conditions": [], "time": "current"}
        if prompt_version.startswith("qa20-answer"):
            return {"answer": self.drafts.pop(0)}
        ids = [line[2:].split(":")[0] for line in user.split("Items to check:\n")[1].splitlines()]
        passed = self.passes.pop(0)
        return {"results": [{"id": item, "reason": "r", "passed": passed, "sentence": "s", "fix": "f"} for item in ids]}


def test_source_id_matches_the_evaluator():
    item = record()
    blob = json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    assert source_id(item) == sha256(blob.encode()).hexdigest()[:24]


def test_run_case_answers_with_a_valid_citation():
    item = record()
    rows, stats = run_case(PacketLLM(), case(item))
    row = rows[0]
    assert row["id"] == "legacy-x/qa-0"
    assert (row["answer"], row["path"], row["status"]) == ("full [1]", "checked", "ok")
    cited = row["citations"][0]
    assert cited["source_id"] == source_id(item)
    assert TEXT[cited["start"]:cited["end"]] == cited["quote"]
    assert stats["claims"] == 1


def test_only_the_author_approves():
    rows, _ = run_case(PacketLLM(), case(record()))
    assert rows[0]["response"]["status"] == "answered"
    assert rows[0]["response"]["evidence"][0]["approved_by"] == ["Git docs"]


def test_opposing_records_stay_in_conflict():
    class TwoValues(PacketLLM):
        def complete_json(self, **kwargs):
            if kwargs["prompt_version"].startswith("structure"):
                self.value = "full" if "Eli" not in kwargs["user"] else "compact"
            return super().complete_json(**kwargs)

    eli = f"Eli says {QUOTE} is wrong and writes a long enough note. " * 8
    rows, _ = run_case(TwoValues(drafts=["full [1] or compact [2]"]), case(record(), record("loc2", "Eli", eli)))
    assert rows[0]["response"]["status"] == "conflict"


def test_failed_check_is_fixed_then_passes():
    llm = PacketLLM(drafts=["bad [1]", "full [1]"], passes=[False, True])
    rows, _ = run_case(llm, case(record()))
    assert (rows[0]["answer"], rows[0]["path"]) == ("full [1]", "checked")
    last = [user for version, user in llm.prompts if version.startswith("qa20-answer")][-1]
    assert "Your draft failed the check: bad [1]" in last


def test_three_failed_checks_fall_back_to_safe_answer():
    llm = PacketLLM(drafts=["a [1]", "b [1]", "c [1]"], passes=[False, False, False])
    rows, _ = run_case(llm, case(record()))
    assert rows[0]["path"] == "safe_answer"
    assert rows[0]["answer"].startswith("full [1]")
    assert rows[0]["citations"][0]["number"] == 1


def test_server_error_on_answer_uses_safe_answer():
    class Down(PacketLLM):
        def complete_json(self, **kwargs):
            if kwargs["prompt_version"].startswith("qa20-answer"):
                raise LLMError("down")
            return super().complete_json(**kwargs)

    assert run_case(Down(), case(record()))[0][0]["path"] == "safe_answer"


def test_interpret_failure_is_reported_as_error():
    class Down(PacketLLM):
        def complete_json(self, **kwargs):
            if kwargs["prompt_version"].startswith("interpret"):
                raise LLMError("down")
            return super().complete_json(**kwargs)

    row = run_case(Down(), case(record()))[0][0]
    assert (row["status"], row["answer"], row["citations"]) == ("error", "", [])


def test_write_answer_with_no_evidence_still_runs_the_check():
    response = {"question": "q", "status": "no_evidence", "groups": [], "evidence": [], "notes": [], "previous": [],
                "answer_rules": ["rule"], "safe_answer": "근거 없음"}
    assert write_answer(PacketLLM(drafts=["no evidence"]), response) == ("no evidence", "checked")


def test_citations_keep_only_used_numbers_and_drop_unknown_quotes():
    records = {"loc1": record()}
    response = {"evidence": [{"ref": 1, "doc": "loc1", "quote": QUOTE}, {"ref": 2, "doc": "loc1", "quote": QUOTE},
                             {"ref": 3, "doc": "loc1", "quote": "없는 문장"}]}
    found, dropped = citations("답 [2] [3]", response, records)
    assert [item["number"] for item in found] == [2]
    assert dropped == 1


def test_citation_uses_exact_source_text_when_spacing_differs():
    response = {"evidence": [{"ref": 1, "doc": "loc1", "quote": "default style is full"}]}
    found, _ = citations("답 [1]", response, {"loc1": record()})
    assert found[0]["quote"] == QUOTE


def test_chains_group_cases_with_the_same_first_record():
    git, other = case(record("git")), case(record("pep"))
    assert chains([git, other, case(record("git"))]) == [[git, case(record("git"))], [other]]
