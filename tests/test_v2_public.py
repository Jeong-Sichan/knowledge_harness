"""공개 데이터 변환과 채점 테스트. 서버 없이 돈다."""
from eval.layer1_public import kind_correct, score_note, value_matches
from eval.public_data import sentence_at, unescape_xml
from harness_v2.interpret import interpret_question
from harness_v2.llm import LLMError


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def complete_json(self, **kwargs):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def claim(value, topic="depth", statement="", conditions=()):
    return {"value": value, "topic": topic, "statement": statement, "conditions": list(conditions)}


def test_value_matches_numbers_and_words():
    assert value_matches("2617.4 m", "2617.4 metres")
    assert not value_matches("2617.4 m", "2617.5 m")
    assert value_matches("2619.6 and 2614.7 m", "2619.6, 2614.7")
    assert value_matches("Five", "five samples")


def test_partial_number_does_not_match():
    assert not value_matches("61", "2617")


def test_entity_must_be_in_the_matching_claim():
    gold = [{"quantity": "5 m", "entity": "peak", "qualifier": None}]
    assert score_note(gold, [claim("5 m", topic="brief_peak")])["entity"] == [1, 1]
    assert score_note(gold, [claim("5 m"), claim("9 m", topic="peak")])["entity"] == [0, 1]


def test_qualifier_found_in_conditions():
    gold = [{"quantity": "5 m", "entity": None, "qualifier": "in Apectodinium"}]
    found = claim("5 m", conditions=[{"key": "taxon", "value": "in Apectodinium"}])
    assert score_note(gold, [found])["qualifier"] == [1, 1]


def test_missing_fields_are_not_counted():
    gold = [{"quantity": "5 m", "entity": None, "qualifier": None}]
    assert score_note(gold, [])== {"quantity": [0, 1], "entity": [0, 0], "qualifier": [0, 0]}


def test_kind_rules():
    assert kind_correct("decision", ["observation", "decision"])
    assert not kind_correct("observation", ["observation", "decision"])
    assert kind_correct("observation", ["observation"])
    assert not kind_correct("decision", [])


def test_sentence_at_finds_containing_sentence():
    text = "First one here. The depth was 5 m today. Last one."
    assert sentence_at(text, text.index("5 m")) == "The depth was 5 m today."
    assert sentence_at(text, text.index("Last")) == "Last one."


def test_unescape_xml():
    assert unescape_xml("a &lt; b &amp; c") == "a < b & c"


def test_interpret_normalizes_topic_and_key():
    reply = {"topics": ["Nationality"], "conditions": [{"key": "Player", "value": "Terrence Ross"}], "time": "current"}
    result = interpret_question(FakeLLM(reply), "q", ["Nationality", "Player"])
    assert result.topics == ["nationality"]
    assert result.conditions == {"player": "Terrence Ross"}


def test_interpret_reports_server_error():
    assert interpret_question(FakeLLM(LLMError("down")), "q", ["a"]).error == "down"
