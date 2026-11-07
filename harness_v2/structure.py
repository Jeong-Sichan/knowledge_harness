"""D4 구조화. 서버 LLM이 자유 글에서 주장을 뽑고, 인용은 규칙으로 검사한다.

인용이 원문에 없으면 오류와 가장 비슷한 구간을 돌려주고 최대 2번 다시 묻는다.
그래도 틀린 주장은 저장하지 않는다(D3 ④).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .llm import LLMError
from .quote import auto_quote, find_quote

PROMPT_VERSION = "structure-v3"
FIX_PROMPT_VERSION = "quote-fix-v2"
MAX_RETRIES = 2

SYSTEM = """You extract claims from a team note. A claim is one statement under one set of conditions.

For each claim give:
- kind: "decision" if the team adopted, rejected, or postponed something ("we will use X", "we won't do Y"). "observation" for a measurement, comparison, or observed result. If unsure, use "observation". If a sentence contains both, write two claims.
- topic: a short snake_case name for what the claim is about. Reuse a name from the existing topics if one means the same thing.
- value: the claim's answer for that topic, kept short. If the claim states a number, the value is that number with its unit and nothing else. Never put a description in value.
- conditions: key/value pairs under which the claim holds, only if the note states them. Do not guess. Reuse a key from the existing condition keys if one means the same thing.
- statement: one sentence stating the claim, in the note's language.
- quote: one short passage, at most one sentence, copied character for character from the note. Keep spacing, punctuation, and quotation marks exactly. Do not join text from different places, paraphrase, translate, use "...", or fix typos.

Extract at most 8 claims, keeping the most important ones. Skip greetings and small talk. Keep your reasoning brief."""

FIX_SYSTEM = """A quote must be copied character for character from the note, including spacing, punctuation, and quotation marks. The quote below is not in the note.
Return a shorter quote, at most one sentence, copied exactly from the note, that supports the claim. Keep your reasoning brief."""

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["observation", "decision"]},
            "topic": {"type": "string"},
            "value": {"type": "string"},
            "conditions": {"type": "array", "items": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                "required": ["key", "value"],
            }},
            "statement": {"type": "string"},
            "quote": {"type": "string"},
        },
        "required": ["kind", "topic", "value", "conditions", "statement", "quote"],
    }}},
    "required": ["claims"],
}
FIX_SCHEMA = {"type": "object", "properties": {"quote": {"type": "string"}}, "required": ["quote"]}


def normalize_name(name: str) -> str:
    """대소문자·띄어쓰기·`_`·`-`만 다르면 같은 이름이다 (D4 ③)."""
    return re.sub(r"[\s_\-]+", "_", name.strip().lower()).strip("_")


@dataclass
class ExtractedClaim:
    data: dict
    ok: bool
    first_try_ok: bool
    retries: int
    start: int | None = None
    end: int | None = None


@dataclass
class ExtractResult:
    claims: list[ExtractedClaim] = field(default_factory=list)
    error: str | None = None

    @property
    def stored(self) -> list[ExtractedClaim]:
        return [claim for claim in self.claims if claim.ok]


def _fix_prompt(note: str, claim: dict, nearest: str) -> str:
    return (f"Note:\n{note}\n\nClaim: {claim['statement']}\n"
            f"Quote not found in the note: {claim['quote']}\n"
            f"Closest passage in the note: {nearest}")


def _settle_quote(llm, note: str, claim: dict) -> ExtractedClaim:
    found = find_quote(note, claim["quote"])
    first_try_ok = found.ok
    retries = 0
    while not found.ok and retries < MAX_RETRIES:
        retries += 1
        try:
            reply = llm.complete_json(prompt_version=f"{FIX_PROMPT_VERSION}#{retries}", system=FIX_SYSTEM,
                                      user=_fix_prompt(note, claim, found.nearest or ""), schema=FIX_SCHEMA)
        except LLMError:
            break
        claim = {**claim, "quote": reply["quote"]}
        found = find_quote(note, claim["quote"])
    return ExtractedClaim(claim, found.ok, first_try_ok, retries, found.start, found.end)


def extract_claims(llm, note: str, existing_topics: list[str] | None = None,
                   existing_keys: list[str] | None = None) -> ExtractResult:
    topics = ", ".join(existing_topics or []) or "(none yet)"
    keys = ", ".join(existing_keys or []) or "(none yet)"
    try:
        reply = llm.complete_json(prompt_version=PROMPT_VERSION, system=SYSTEM, schema=CLAIMS_SCHEMA,
                                  user=f"Existing topics: {topics}\nExisting condition keys: {keys}\n\nNote:\n{note}")
    except LLMError as exc:
        return ExtractResult(error=str(exc))

    whole_note = auto_quote(note)
    claims = []
    for raw in reply["claims"]:
        claim = {**raw, "topic": normalize_name(raw["topic"])}
        if whole_note is not None:
            claim["quote"] = whole_note
            claims.append(ExtractedClaim(claim, True, True, 0, 0, len(note)))
        else:
            claims.append(_settle_quote(llm, note, claim))
    return ExtractResult(claims=claims)
