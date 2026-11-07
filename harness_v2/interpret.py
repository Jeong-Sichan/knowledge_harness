"""D8 ① 질문 해석. 서버 LLM이 기존 주제 목록을 보고 주제·조건·질문 종류를 뽑는다."""
from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMError
from .structure import normalize_name

PROMPT_VERSION = "interpret-v2"

SYSTEM = """You read a question about team records and say what it asks for.

- topics: the existing topics whose answer the question wants, copied exactly from the list. Do not list a topic only because the question uses it as a condition. Use an empty list if none fits.
- conditions: key/value pairs the question states as given facts. Use a key from the existing condition keys when one fits, and copy the value as written in the question. The thing the question asks for is not a condition. Do not guess conditions the question does not state.
- time: "history" only if the question explicitly asks how something changed or what it was before. Past tense alone is not history. Otherwise "current".

Keep your reasoning brief."""

SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {"type": "array", "items": {"type": "string"}},
        "conditions": {"type": "array", "items": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
            "required": ["key", "value"],
        }},
        "time": {"type": "string", "enum": ["current", "history"]},
    },
    "required": ["topics", "conditions", "time"],
}


@dataclass
class Interpretation:
    topics: list[str] = field(default_factory=list)
    conditions: dict[str, str] = field(default_factory=dict)
    time: str = "current"
    error: str | None = None


def interpret_question(llm, question: str, topics: list[str], condition_keys: list[str] | None = None) -> Interpretation:
    keys = ", ".join(condition_keys or []) or "(none yet)"
    listed = ", ".join(topics) or "(none yet)"
    try:
        reply = llm.complete_json(prompt_version=PROMPT_VERSION, system=SYSTEM, schema=SCHEMA,
                                  user=f"Existing topics: {listed}\nExisting condition keys: {keys}\n\nQuestion: {question}")
    except LLMError as exc:
        return Interpretation(error=str(exc))
    conditions = {normalize_name(pair["key"]): pair["value"] for pair in reply["conditions"]}
    return Interpretation([normalize_name(topic) for topic in reply["topics"]], conditions, reply["time"])
