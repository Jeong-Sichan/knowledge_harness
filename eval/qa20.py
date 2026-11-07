"""팀원 QA20 패키지를 하네스 v2 전체 흐름으로 돌린다. 채점은 사람이 evaluate.py로 한다.

시험 설정(2026-11-06 결정):
- 기록 묶음마다 빈 저장소에서 시작한다. 입력 순서를 지킨다.
- 주장마다 작성자 본인 승인만 넣는다. 충돌 상대의 승인은 넣지 않아 상충 기록은 충돌로 남는다.
- 답은 같은 서버 LLM이 `ask` 응답만 보고 쓴다. check_answer 실패 시 2번 고치고, 그래도 실패하면 safe_answer를 쓴다.
- 질문 JSON에서 문장만 꺼낸다. 모든 기록이 as_of 이전이라 as_of로 거를 것이 없다.

실행: python -m eval.qa20 --data <qa20 폴더> --out <결과 폴더> [--only <기록 묶음 id>]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

from harness_v2.check import check_answer
from harness_v2.interpret import PROMPT_VERSION as INTERPRET_VERSION
from harness_v2.llm import LLMError, ServerLLM
from harness_v2.model import APPROVE, Vote
from harness_v2.quote import find_quote
from harness_v2.respond import ERROR, ask_context, respond
from harness_v2.store import Store
from harness_v2.structure import PROMPT_VERSION as STRUCTURE_VERSION
from harness_v2.submit import submit_note

ANSWER_VERSION = "qa20-answer-v1"
MAX_FIXES = 2
PROGRESS_EVERY = 25

ANSWER_SYSTEM = """You are a team member's AI assistant. Answer the question using only the harness response you are given.
Follow every answer rule. Answer exactly what is asked, in the language of the question, in one or two short sentences.
Cite evidence numbers such as [1] after each fact. Do not add facts from outside the evidence. Keep your reasoning brief."""
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def source_id(record: dict) -> str:
    """evaluate.py와 같은 직렬화."""
    blob = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return sha256(blob.encode()).hexdigest()[:24]


def answer_prompt(response: dict, draft: str | None, problems: list[dict]) -> str:
    lines = [f"Question: {response['question']}", f"Status: {response['status']}", "", "Evidence:"]
    for item in response["evidence"]:
        approved = ", ".join(item["approved_by"]) or "nobody"
        lines.append(f"[{item['ref']}] {item['statement']} Value: {item['value']}. Conditions: {item['conditions']}. "
                     f"Quote: {item['quote']}. State: {item['state']}. Approved by: {approved}. "
                     f"Conditions unverified: {item['unverified']}. Previous decision: {item['previous']}.")
    if not response["evidence"]:
        lines.append("(none)")
    lines += ["", "Notes:", *response["notes"], "", "Answer rules:", *response["answer_rules"]]
    if draft is not None:
        lines += ["", f"Your draft failed the check: {draft}", "Problems:"]
        lines += [f"- {problem['type']}: {problem['sentence']} Fix: {problem['fix']}" for problem in problems]
    return "\n".join(lines)


def write_answer(llm, response: dict) -> tuple[str, str]:
    """(답, 경로). 경로는 checked, safe_answer, error 중 하나다."""
    if response["status"] == ERROR:
        return "", "error"
    context = ask_context(response)
    draft, problems = None, []
    for _ in range(MAX_FIXES + 1):
        try:
            reply = llm.complete_json(prompt_version=ANSWER_VERSION, system=ANSWER_SYSTEM, schema=ANSWER_SCHEMA,
                                      user=answer_prompt(response, draft, problems))
        except LLMError:
            break
        draft = reply["answer"]
        checked = check_answer(llm, context, draft)
        if checked["pass"]:
            return draft, "checked"
        if checked["error"]:
            break
        problems = checked["problems"]
    return response["safe_answer"], "safe_answer"


def citations(answer: str, response: dict, records: dict[str, dict]) -> tuple[list[dict], int]:
    """답에 쓴 번호만 원문 위치로 바꾼다. 원문에서 못 찾으면 뺀다. (인용 목록, 뺀 수)"""
    used = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
    found, dropped = [], 0
    for item in response["evidence"]:
        if item["ref"] not in used:
            continue
        record = records[item["doc"]]
        text = record["source"]["text"]
        located = find_quote(text, item["quote"])
        if not located.ok:
            dropped += 1
            continue
        found.append({"number": item["ref"], "source_id": source_id(record), "quote": text[located.start:located.end],
                      "start": located.start, "end": located.end})
    return found, dropped


def run_case(llm, case: dict) -> tuple[list[dict], dict]:
    """기록 묶음 하나를 빈 저장소에서 돌린다. (문항 결과, 통계)"""
    store = Store()
    stats = Counter()
    records: dict[str, dict] = {}
    for event in case["events"]:
        if event["operation"] == "import_history":
            for number, record in enumerate(event["records"], 1):
                source = record["source"]
                records[source["location"]] = record
                result = submit_note(llm, store, source["text"], record["owner"], doc=source["location"],
                                     location=source["location"], created_at=record["observed_at"])
                stats["records"] += 1
                stats["extract_errors"] += len(result.errors)
                stats["no_claims"] += result.is_new and not result.claims
                for claim in result.claims:
                    store.add_vote(Vote(claim.id, claim.author, APPROVE, record["observed_at"]))
                if number % PROGRESS_EVERY == 0:
                    print(case["id"], number, "records", len(store.claims), "claims", flush=True)
    stats["claims"] = len(store.claims)
    stats["topics"] = len(store.topics())
    stats["condition_keys"] = len(store.condition_keys())

    rows = []
    for event in case["events"]:
        if event["operation"] != "ask":
            continue
        question = json.loads(event["question"])["question"]
        response = respond(llm, store, question)
        answer, path = write_answer(llm, response)
        cited, dropped = citations(answer, response, records)
        stats["dropped_citations"] += dropped
        rows.append({"id": f"{case['id']}/{event['label']}", "answer": answer, "citations": cited,
                     "status": "error" if path == "error" else "ok", "path": path, "response": response})
        print(rows[-1]["id"], response["status"], path, flush=True)
    return rows, dict(stats)


def chains(cases: list[dict]) -> list[list[dict]]:
    """같은 기록으로 시작하는 묶음은 이어서 돌린다. 앞 묶음의 호출 기록을 다시 쓰기 위해서다."""
    groups: dict[str, list[dict]] = {}
    for case in cases:
        first = next(event for event in case["events"] if event["operation"] == "import_history")
        groups.setdefault(first["records"][0]["source"]["location"], []).append(case)
    return list(groups.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()

    packet = json.loads((args.data / "data" / "inputs.json").read_text(encoding="utf-8"))
    cases = [case for case in packet["cases"] if not args.only or case["id"] in args.only]
    llm = ServerLLM()

    def run_chain(chain: list[dict]) -> list[tuple[dict, list[dict], dict]]:
        return [(case, *run_case(llm, case)) for case in chain]

    groups = chains(cases)
    with ThreadPoolExecutor(len(groups)) as pool:
        finished = [item for chain in pool.map(run_chain, groups) for item in chain]
    order = {case["id"]: number for number, case in enumerate(cases)}
    finished.sort(key=lambda item: order[item[0]["id"]])

    args.out.mkdir(parents=True, exist_ok=True)
    rows = [row for _, case_rows, _ in finished for row in case_rows]
    with open(args.out / "predictions.jsonl", "w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps({key: row[key] for key in ("id", "answer", "citations", "status")}, ensure_ascii=False) + "\n")
    with open(args.out / "details.jsonl", "w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"model": llm.model, "thinking": llm.thinking, "prompts": [STRUCTURE_VERSION, INTERPRET_VERSION, ANSWER_VERSION],
               "cases": {case["id"]: stats for case, _, stats in finished},
               "status": Counter(row["response"]["status"] for row in rows),
               "path": Counter(row["path"] for row in rows), "llm": llm.stats}
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if not llm.stats["calls"] and not llm.stats["cache_hits"]:
        raise SystemExit("LLM 호출이 한 건도 성공하지 못했다")


if __name__ == "__main__":
    main()
