"""D8 ⑤·D9 ① `ask` 응답 조립. 해석 1회 뒤 규칙으로 근거 번호, 답변 규칙, `safe_answer`를 만든다."""
from __future__ import annotations

import hashlib
import json

from .approval import APPROVED
from .ask import ANSWERED, BY_CONDITION, CONFLICT, NO_EVIDENCE, ONLY_UNAPPROVED, SOURCE_MISSING, Entry, Group, evaluate
from .check import AskContext
from .conditions import clean
from .interpret import interpret_question
from .relations import recitation_groups
from .store import Store
from .submit import shown_names

MAX_EVIDENCE = 10
QUESTION_TOPICS_SHOWN = 100
ERROR = "error"
STATUS_ORDER = [CONFLICT, ONLY_UNAPPROVED, ANSWERED, NO_EVIDENCE]

BASE_RULES = ["Use only the evidence below and cite it with numbers such as [1].",
              "Do not give a result from other conditions as the answer to this question's conditions."]
STATUS_RULES = {
    ANSWERED: "State the value and name the people who approved it.",
    CONFLICT: "The records disagree. Give every side with its approval state. Do not pick one.",
    ONLY_UNAPPROVED: "This record is not approved yet. Say so and do not call it a team fact.",
    NO_EVIDENCE: "There is no evidence. Say so and do not state a value.",
}
UNVERIFIED_RULE = "Some evidence does not state the asked conditions. Say that its conditions are unverified."


def bundles(group: Group) -> list[list[Entry]]:
    """값이 같고 인용이 겹치는 주장은 근거 하나로 묶는다. 승인된 묶음을 앞에 둔다."""
    result = []
    for value in sorted({clean(entry.claim.value) for entry in group.entries}):
        entries = {entry.claim.id: entry for entry in group.entries if clean(entry.claim.value) == value}
        linked = recitation_groups([entry.claim for entry in entries.values()])
        result.append(sorted(([entries[claim.id] for claim in members] for members in linked),
                             key=lambda members: not any(entry.state == APPROVED for entry in members)))
    return result


def pick_evidence(sections: list[tuple[str, Group]]) -> tuple[list[tuple[str, list[Entry]]], int]:
    """묶음과 값을 번갈아 고른다. 한도에 걸려도 충돌의 한쪽만 남지 않게 한다."""
    queues = [[(topic, members) for members in queue] for topic, group in sections for queue in bundles(group)]
    chosen, seen = [], set()
    while any(queues) and len(chosen) < MAX_EVIDENCE:
        for queue in queues:
            while queue and len(chosen) < MAX_EVIDENCE:
                topic, members = queue.pop(0)
                if members[0].claim.id not in seen:
                    seen.add(members[0].claim.id)
                    chosen.append((topic, members))
                    break
    return chosen, sum(len(queue) for queue in queues)


def evidence_item(ref: int, topic: str, members: list[Entry]) -> dict:
    entry = members[0]
    claim = entry.claim
    first = claim.evidence[0]
    return {"ref": ref, "topic": topic, "kind": claim.kind, "value": claim.value, "statement": claim.statement,
            "conditions": claim.conditions, "quote": first.quote, "doc": first.doc, "start": first.start,
            "end": first.end, "author": claim.author, "state": entry.state,
            "approved_by": sorted({name for member in members for name in member.approvers}),
            "unverified": entry.unverified, "previous": entry.previous, "source_check": entry.source,
            "claim_id": claim.id, "recited": len(members) - 1}


def item_text(item: dict) -> str:
    approved = f"승인: {', '.join(item['approved_by'])}" if item["state"] == APPROVED else "승인 전"
    marks = [approved] + ["조건 미확인"] * item["unverified"] + ["이전 결정"] * item["previous"]
    return f"{item['value']} [{item['ref']}] ({', '.join(marks)})"


def group_line(group: dict, items: list[dict]) -> str:
    label = ", ".join(f"{key}={value}" for key, value in group["conditions"].items())
    prefix = f"{label}: " if label else ""
    body = " / ".join(item_text(item) for item in items)
    if group["status"] == CONFLICT:
        return f"{prefix}기록이 엇갈립니다. {body}"
    if group["status"] == ONLY_UNAPPROVED:
        return f"{prefix}아직 승인되지 않은 기록에 따르면 {body}"
    return f"{prefix}{body}, 독립 근거 {group['independent']}개"


def error_response(question: str, reason: str) -> dict:
    return {"ask_id": None, "question": question, "understood_as": None, "status": ERROR, "groups": [], "evidence": [],
            "notes": [reason], "previous": [], "answer_rules": [],
            "safe_answer": "지금 답할 수 없습니다. 모델 서버를 확인해야 합니다."}


def respond(llm, store: Store, question: str) -> dict:
    topics, keys = store.topics(), store.condition_keys()
    parsed = interpret_question(llm, question, shown_names(question, topics, QUESTION_TOPICS_SHOWN),
                                shown_names(question, keys, QUESTION_TOPICS_SHOWN))
    if parsed.error:
        return error_response(question, parsed.error)
    aliases = store.aliases
    asked_topics = list(dict.fromkeys(aliases["topic"].get(topic, topic) for topic in parsed.topics))
    known = [topic for topic in asked_topics if topic in topics]
    conditions = {aliases["key"].get(key, key): value for key, value in parsed.conditions.items()}
    claims, latest = store.all_claims(), store.latest_texts()
    results = {topic: evaluate(topic, claims, store.votes, conditions, parsed.time, latest) for topic in known}

    sections = [(topic, group) for topic, result in results.items() for group in result.groups]
    chosen, omitted = pick_evidence(sections)
    evidence = [evidence_item(ref, topic, members) for ref, (topic, members) in enumerate(chosen, 1)]
    refs = {item["claim_id"]: item["ref"] for item in evidence}
    groups = [{"topic": topic, "conditions": group.conditions, "status": group.status,
               "independent": group.independent,
               "refs": sorted({refs[entry.claim.id] for entry in group.entries if entry.claim.id in refs})}
              for topic, group in sections]
    status = NO_EVIDENCE if not groups else groups[0]["status"] if len(groups) == 1 else BY_CONDITION

    previous = [f"{claim.value}: {claim.statement}" for result in results.values() for claim in result.previous]
    notes = [f"이전 결정: {line}" for line in previous]
    for result in results.values():
        notes += [f"조건이 다름: {claim.value} ({claim.conditions})" for claim in result.different_conditions]
        notes += [f"이 주제와 관련 없어 무시한 조건: {key}" for key in result.ignored_keys]
    notes += [f"[{item['ref']}] 최신 원문에서 사라짐, 재확인 필요" for item in evidence if item["source_check"] == SOURCE_MISSING]
    if omitted:
        notes.append(f"근거 {omitted}개는 한도 때문에 생략함")

    statuses = {group["status"] for group in groups} or {NO_EVIDENCE}
    rules = BASE_RULES + [STATUS_RULES[item] for item in STATUS_ORDER if item in statuses]
    if any(item["unverified"] for item in evidence):
        rules.append(UNVERIFIED_RULE)
    by_ref = {item["ref"]: item for item in evidence}
    lines = [group_line(group, [by_ref[ref] for ref in group["refs"]]) for group in groups]
    safe_answer = "\n".join(lines) or "이 질문에 답할 근거가 없습니다."
    extra = [note for note in notes if note.startswith(("이전 결정", "조건이 다름"))]
    understood = {"topics": known, "conditions": conditions, "time": parsed.time}
    body = json.dumps([question, understood, sorted(refs)], ensure_ascii=False, sort_keys=True)
    return {"ask_id": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16], "question": question,
            "understood_as": understood, "status": status, "groups": groups, "evidence": evidence, "notes": notes,
            "previous": previous, "answer_rules": rules, "safe_answer": "\n".join([safe_answer, *extra])}


def ask_context(response: dict) -> AskContext:
    """D9 검사 입력. 조건별 묶음이면 가장 엄격한 상태의 체크리스트를 쓴다."""
    statuses = {group["status"] for group in response["groups"]}
    status = next((item for item in STATUS_ORDER if item in statuses), NO_EVIDENCE)
    evidence = {item["ref"]: f"{item['statement']} Value: {item['value']}. Quote: {item['quote']}. State: {item['state']}."
                for item in response["evidence"]}
    return AskContext(response["question"], status, evidence, any(item["unverified"] for item in response["evidence"]),
                      response["previous"])
