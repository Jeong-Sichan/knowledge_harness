"""D15 1층: 인용과 답 검사 측정. 정답 표시 없이 잴 수 있는 두 부품만 다룬다.

데이터 (읽기만 함)
- EverMemBench-Dynamic: 채팅 메시지, 근거 위치, 객관식 오답
- WikiContradict: 서로 모순되는 문단 쌍

좋은 답과 나쁜 답은 이 데이터에서 규칙으로 만든다. 사람이 쓴 답이 아니므로 D9 체크리스트 일부만 시험한다.
개발용/시험용은 id 해시로 나눈다(3개 중 1개가 개발용). 지시문 수정은 개발용만 보고 한다.

실행: python -m eval.layer1 --data-root <datasets-v1> --split dev --out <결과.json>
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import random
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from harness_v2.check import PROMPT_VERSION as CHECK_VERSION
from harness_v2.check import AskContext, check_answer
from harness_v2.llm import ServerLLM
from harness_v2.quote import AUTO_QUOTE_MAX
from harness_v2.structure import PROMPT_VERSION as STRUCTURE_VERSION
from harness_v2.structure import extract_claims

MAX_NOTE_CHARS = 6000
LIMITS = {"dev": {"note": 20, "check": 30}, "test": {"note": 40, "check": 60}}
PROPOSED_BAR = {"quote": 0.95, "bad_caught": 0.90, "good_passed": 0.90}  # D15 제안값, 시험용 측정 전에 고정


def split_of(item_id: str) -> str:
    return "dev" if int(hashlib.sha256(item_id.encode()).hexdigest(), 16) % 3 == 0 else "test"


def take(items: list, split: str, limit: int, key) -> list:
    chosen = [item for item in items if split_of(key(item)) == split]
    random.Random(f"layer1-{split}").shuffle(chosen)
    return chosen[:limit]


def parse_indices(text: str) -> set[int]:
    """"1, 4-6" 형식의 message_index를 번호 집합으로 바꾼다."""
    out: set[int] = set()
    for part in str(text).split(","):
        part = part.strip()
        if "-" in part:
            low, high = part.split("-")
            out.update(range(int(low), int(high) + 1))
        elif part:
            out.add(int(part))
    return out


def change_number(answer: str) -> str | None:
    """답의 마지막 숫자 끝자리를 바꾼다. 숫자가 없으면 None."""
    matches = list(re.finditer(r"\d+", answer))
    if not matches:
        return None
    last = matches[-1]
    digits = last.group()
    changed = digits[:-1] + str((int(digits[-1]) + 3) % 10)
    return answer[:last.start()] + changed + answer[last.end():]


@dataclass
class Case:
    case_id: str
    kind: str
    label: str  # good / bad
    ctx: AskContext
    answer: str


def load_emb(root: Path) -> tuple[list[dict], list[dict]]:
    """(질문 목록, 그룹·날짜별 노트 목록). 질문에는 근거 본문 evidence를 붙인다."""
    questions, notes = [], []
    for folder in sorted(glob.glob(str(root / "EverMemBench-Dynamic" / "0*"))):
        topic = Path(folder).name
        days = json.load(open(Path(folder) / "dialogue.json", encoding="utf-8"))
        by_day = {day["date"]: day["dialogues"] for day in days}
        for date, groups in by_day.items():
            for group, messages in groups.items():
                if messages:
                    text = "\n".join(f"{m['speaker']}: {m['dialogue']}" for m in messages)
                    notes.append({"id": f"emb-{topic}-{date}-{group}", "text": text})
        for item in json.load(open(Path(folder) / f"qa_{topic}.json", encoding="utf-8")):
            lines = []
            for ref in item["R"]:
                wanted = parse_indices(ref["message_index"])
                for message in by_day.get(ref["date"], {}).get(ref["group"]) or []:
                    if message["message_index"] in wanted:
                        lines.append(f"{message['speaker']}: {message['dialogue']}")
            questions.append({**item, "evidence": "\n".join(lines)})
    return questions, notes


def load_wiki(root: Path) -> list[dict]:
    path = root / "Wikipedia_contradict_benchmark" / "WikiContradict_dataset_v1_rag_qa.csv"
    with open(path, encoding="utf-8", errors="replace") as file:
        return list(csv.DictReader(file))


def build_notes(root: Path, split: str) -> list[dict]:
    """300자 이하는 자동 인용이라 시험이 안 되므로 뺀다."""
    limit = LIMITS[split]["note"]
    _, emb = load_emb(root)
    emb = [note for note in emb if AUTO_QUOTE_MAX < len(note["text"]) <= MAX_NOTE_CHARS]
    wiki = [{"id": f"wiki-{row['question_ID']}", "text": row["merged_context"]} for row in load_wiki(root)]
    seen, unique = set(), []
    for note in wiki:
        if len(note["text"]) > AUTO_QUOTE_MAX and note["text"] not in seen:
            seen.add(note["text"])
            unique.append(note)
    key = lambda note: note["id"]
    return take(emb, split, limit, key) + take(unique, split, limit, key)


def build_cases(root: Path, split: str) -> list[Case]:
    limit = LIMITS[split]["check"]
    questions, _ = load_emb(root)
    facts = [q for q in questions if q["id"].startswith("F_SH") and q["evidence"]]
    updates = [q for q in questions if q["id"].startswith("MA_U") and q["evidence"] and q.get("options")]
    key_q = lambda q: q["id"]
    cases: list[Case] = []

    def pair(case_id: str, kind: str, ctx: AskContext, good: str, bad: str) -> None:
        cases.append(Case(case_id, kind, "good", ctx, good))
        cases.append(Case(case_id, kind, "bad", ctx, bad))

    for number, row in enumerate(take(load_wiki(root), split, limit, lambda r: f"wiki-{r['question_ID']}")):
        ctx = AskContext(row["question"], "conflict", {1: row["context1"], 2: row["context2"]})
        side, ref = (row["answer1"], 1) if number % 2 == 0 else (row["answer2"], 2)
        good = f"The records conflict. [1] says: {row['answer1']} [2] says: {row['answer2']}"
        pair(f"wiki-{row['question_ID']}", "conflict_one_side", ctx, good, f"{side} [{ref}]")

    numeric = []
    for q in facts:
        changed = change_number(q["A"])
        if changed and changed not in q["evidence"]:
            numeric.append({**q, "changed": changed})
    for q in take(numeric, split, limit, key_q):
        ctx = AskContext(q["Q"], "answered", {1: q["evidence"]})
        pair(q["id"], "changed_number", ctx, f"{q['A']} [1]", f"{q['changed']} [1]")

    for q in take(updates, split, limit, key_q):
        wrong = sorted(key for key in q["options"] if key != q["A"])
        bad_key = random.Random(q["id"]).choice(wrong)
        ctx = AskContext(q["Q"], "answered", {1: q["evidence"]})
        pair(q["id"], "wrong_option", ctx, f"{q['options'][q['A']]} [1]", f"{q['options'][bad_key]} [1]")

    for q in take(facts, split, limit, key_q):
        ctx = AskContext(q["Q"], "only_unapproved", {1: q["evidence"]})
        good = f"According to a record that is not approved yet: {q['A']} [1]. This is not a confirmed team fact."
        pair(f"{q['id']}-unapproved", "unapproved_as_fact", ctx, good, f"The team has confirmed this: {q['A']} [1]")

    for q in take(facts, split, limit, key_q):
        ctx = AskContext(q["Q"], "no_evidence")
        pair(f"{q['id']}-none", "value_without_evidence", ctx,
             "The team records have no evidence for this question.", f"{q['A']}")
    return cases


def rate(hit: int, total: int) -> dict:
    return {"correct": hit, "total": total, "accuracy": round(hit / total, 4) if total else None}


def measure_quote(llm, notes: list[dict], workers: int) -> dict:
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda note: extract_claims(llm, note["text"]), notes))
    claims = [claim for result in results for claim in result.claims]
    failures = [{"note": note["id"], "quote": claim.data["quote"][:200]}
                for note, result in zip(notes, results) for claim in result.claims if not claim.ok]
    return {
        "notes": len(notes),
        "notes_with_error": sum(result.error is not None for result in results),
        "notes_without_claims": sum(result.error is None and not result.claims for result in results),
        "after_retry": rate(sum(claim.ok for claim in claims), len(claims)),
        "first_try": rate(sum(claim.first_try_ok for claim in claims), len(claims)),
        "failures": failures,
    }


def measure_check(llm, cases: list[Case], workers: int) -> dict:
    with ThreadPoolExecutor(workers) as pool:
        verdicts = list(pool.map(lambda case: check_answer(llm, case.ctx, case.answer), cases))
    correct: Counter = Counter()
    total: Counter = Counter()
    wrong = []
    for case, verdict in zip(cases, verdicts):
        right = verdict["error"] is None and verdict["pass"] == (case.label == "good")
        for group in (case.label, f"{case.kind}/{case.label}"):
            total[group] += 1
            correct[group] += right
        if not right:
            wrong.append({"id": case.case_id, "kind": case.kind, "label": case.label, "answer": case.answer[:200],
                          "problems": verdict["problems"], "error": verdict["error"]})
    return {
        "bad_caught": rate(correct["bad"], total["bad"]),
        "good_passed": rate(correct["good"], total["good"]),
        "by_kind": {group: rate(correct[group], total[group]) for group in sorted(total) if "/" in group},
        "errors": sum(verdict["error"] is not None for verdict in verdicts),
        "wrong": wrong,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    llm = ServerLLM()
    notes = build_notes(args.data_root, args.split)
    cases = build_cases(args.data_root, args.split)
    print(f"notes={len(notes)} cases={len(cases)} {Counter(case.kind for case in cases)}", flush=True)
    report = {
        "split": args.split, "model": llm.model, "thinking": llm.thinking, "prompts": [STRUCTURE_VERSION, CHECK_VERSION], "proposed_bar": PROPOSED_BAR,
        "quote": measure_quote(llm, notes, args.workers),
        "check": measure_check(llm, cases, args.workers),
        "llm": llm.stats,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {key: report[key] for key in ("split", "model", "thinking", "llm")}
    summary["quote"] = {k: v for k, v in report["quote"].items() if k != "failures"}
    summary["check"] = {k: v for k, v in report["check"].items() if k != "wrong"}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if not llm.stats["calls"] and not llm.stats["cache_hits"]:
        raise SystemExit("LLM 호출이 한 건도 성공하지 못했다")


if __name__ == "__main__":
    main()
