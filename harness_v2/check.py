"""D9 답 단계 검사. 규칙으로 근거 번호와 민감 정보를 보고, 서버 LLM이 상태별 체크리스트를 본다.

체크리스트 항목에 답이 없으면 통과로 치지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .llm import LLMError
from .pii import PATTERNS

PROMPT_VERSION = "check-v2"

ALWAYS = {
    "no_unsupported": "The facts, numbers, and names the answer gives appear in or follow from the evidence. Do not fail an answer for its wording or for restating the record status.",
    "condition_match": "The answer does not present a result from different conditions as the answer to the question's conditions.",
}
CONFLICT_SUPPORT = "Each side the answer gives follows from the evidence it cites. A short answer such as Yes or No answers the question and does not need to be quoted."
BY_STATUS = {
    "conflict": {"both_sides": "The answer gives both conflicting sides. An answer that gives only one side fails this item, even if that side is in the evidence."},
    "only_unapproved": {"not_stated_as_fact": "The answer says the record is not approved yet. Words such as confirmed, decided, or team fact that assert it as settled fail this item."},
    "no_evidence": {"no_value_asserted": "The answer states that there is no evidence and does not assert a specific value."},
}
UNVERIFIED = {"unverified_disclosed": "The answer discloses that the evidence's conditions are unverified."}
PREVIOUS = {"no_old_as_current": "The answer does not present a previous decision as the current one."}

SYSTEM = """You check a draft answer against the evidence given to it. You do not judge writing style.
Check each listed item separately, using only the evidence and the item's wording. Keep your reasoning brief.
For each item write reason first, then passed. Set passed to false only if the answer breaks that item.
If an item fails, give the offending sentence and how to fix it. If it passes, leave sentence and fix empty."""

SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "reason": {"type": "string"},
            "passed": {"type": "boolean"},
            "sentence": {"type": "string"},
            "fix": {"type": "string"},
        },
        "required": ["id", "reason", "passed", "sentence", "fix"],
    }}},
    "required": ["results"],
}


@dataclass
class AskContext:
    question: str
    status: str
    evidence: dict[int, str] = field(default_factory=dict)
    unverified_condition: bool = False
    previous_decisions: list[str] = field(default_factory=list)


def checklist(ctx: AskContext) -> dict[str, str]:
    items = dict(ALWAYS)
    if ctx.status == "conflict":
        items["no_unsupported"] = CONFLICT_SUPPORT
    items.update(BY_STATUS.get(ctx.status, {}))
    if ctx.unverified_condition:
        items.update(UNVERIFIED)
    if ctx.previous_decisions:
        items.update(PREVIOUS)
    return items


def rule_problems(ctx: AskContext, answer: str) -> list[dict]:
    problems = []
    for ref in sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)} - set(ctx.evidence)):
        problems.append({"type": "bad_ref", "sentence": f"[{ref}]", "fix": "Cite only evidence numbers you were given."})
    for kind, pattern in PATTERNS.items():
        if pattern.search(answer):
            problems.append({"type": "sensitive", "sentence": kind, "fix": "Remove the sensitive value."})
    return problems


def _user_prompt(ctx: AskContext, answer: str, items: dict[str, str]) -> str:
    evidence = "\n\n".join(f"[{ref}] {text}" for ref, text in sorted(ctx.evidence.items())) or "(no evidence)"
    listed = "\n".join(f"- {key}: {text}" for key, text in items.items())
    previous = "\n".join(ctx.previous_decisions)
    extra = f"\n\nPrevious decisions, no longer current:\n{previous}" if previous else ""
    return (f"Question: {ctx.question}\nRecord status: {ctx.status}\n\nEvidence:\n{evidence}{extra}\n\n"
            f"Draft answer:\n{answer}\n\nItems to check:\n{listed}")


def check_answer(llm, ctx: AskContext, answer: str) -> dict:
    """{"pass", "problems", "error"}를 돌려준다. 서버 오류면 pass=False, error에 이유."""
    problems = rule_problems(ctx, answer)
    items = checklist(ctx)
    try:
        reply = llm.complete_json(prompt_version=PROMPT_VERSION, system=SYSTEM,
                                  user=_user_prompt(ctx, answer, items), schema=SCHEMA)
    except LLMError as exc:
        return {"pass": False, "problems": problems, "error": str(exc)}
    results = {result["id"]: result for result in reply["results"]}
    for item in items:
        result = results.get(item)
        if result is None:
            problems.append({"type": item, "sentence": "", "fix": "The checker gave no result for this item."})
        elif not result["passed"]:
            problems.append({"type": item, "sentence": result["sentence"], "fix": result["fix"]})
    return {"pass": not problems, "problems": problems, "error": None}
