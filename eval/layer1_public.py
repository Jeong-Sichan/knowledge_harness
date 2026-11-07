"""D15 1층: 주장 뽑기, 질문 해석, 관측/결정 분류를 공개 데이터로 잰다.

입력은 eval.public_data가 만든 JSONL이다.
실행: python -m eval.layer1_public --data <폴더> --split dev --out <결과.json>
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness_v2.interpret import PROMPT_VERSION as INTERPRET_VERSION
from harness_v2.interpret import interpret_question
from harness_v2.llm import ServerLLM
from harness_v2.structure import PROMPT_VERSION as STRUCTURE_VERSION
from harness_v2.structure import extract_claims, normalize_name


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def rate(hit: int, total: int) -> dict:
    return {"correct": hit, "total": total, "accuracy": round(hit / total, 4) if total else None}


def plain(text: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(text).lower()).strip()


def numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", str(text))


def value_matches(gold: str, value: str) -> bool:
    """정답 수치가 값에 있으면 맞다. 숫자가 있으면 숫자를 모두 찾고, 없으면 글자로 찾는다."""
    wanted = numbers(gold)
    if wanted:
        found = numbers(value)
        return all(number in found for number in wanted)
    return plain(gold) in plain(value)


def claim_text(claim: dict) -> str:
    conditions = " ".join(f"{pair['key']} {pair['value']}" for pair in claim["conditions"])
    return plain(f"{claim['topic']} {claim['statement']} {conditions}")


def score_note(gold: list[dict], claims: list[dict]) -> dict:
    """정답 묶음마다 수치가 맞는 주장을 찾고, 그 주장에서 대상과 조건을 확인한다."""
    counts = {key: [0, 0] for key in ("quantity", "entity", "qualifier")}
    for item in gold:
        counts["quantity"][1] += 1
        match = [claim for claim in claims if value_matches(item["quantity"], claim["value"])]
        counts["quantity"][0] += bool(match)
        for key in ("entity", "qualifier"):
            if item[key]:
                counts[key][1] += 1
                counts[key][0] += any(plain(item[key]) in claim_text(claim) for claim in match)
    return counts


def measure_claims(llm, notes: list[dict], workers: int) -> dict:
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda note: extract_claims(llm, note["note"]), notes))
    totals = {key: [0, 0] for key in ("quantity", "entity", "qualifier")}
    misses = []
    for note, result in zip(notes, results):
        claims = [claim.data for claim in result.stored]
        counts = score_note(note["gold"], claims)
        for key, (hit, total) in counts.items():
            totals[key][0] += hit
            totals[key][1] += total
        if counts["quantity"][0] < counts["quantity"][1]:
            misses.append({"id": note["id"], "gold": [item["quantity"] for item in note["gold"]],
                           "values": [claim["value"] for claim in claims], "error": result.error})
    return {
        "notes": len(notes),
        "notes_with_error": sum(result.error is not None for result in results),
        "claims_per_note": round(sum(len(result.stored) for result in results) / max(1, len(notes)), 2),
        **{key: rate(*totals[key]) for key in totals},
        "misses": misses,
    }


def measure_questions(llm, questions: list[dict], workers: int) -> dict:
    def run(item):
        return interpret_question(llm, item["question"], item["topics"], item["topics"])

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(run, questions))
    topic = conditions = both = 0
    wrong = []
    for item, result in zip(questions, results):
        topic_ok = result.error is None and result.topics == [normalize_name(item["topic"])]
        gold = {(normalize_name(key), plain(value)) for key, value in item["conditions"]}
        conditions_ok = result.error is None and {(key, plain(value)) for key, value in result.conditions.items()} == gold
        topic += topic_ok
        conditions += conditions_ok
        both += topic_ok and conditions_ok
        if not (topic_ok and conditions_ok):
            wrong.append({"id": item["id"], "question": item["question"], "gold_topic": item["topic"],
                          "gold_conditions": item["conditions"], "topics": result.topics,
                          "conditions": result.conditions, "error": result.error})
    total = len(questions)
    return {"topic": rate(topic, total), "conditions": rate(conditions, total), "both": rate(both, total),
            "errors": sum(result.error is not None for result in results), "wrong": wrong}


def kind_correct(gold: str, kinds: list[str]) -> bool:
    """결정 문장은 결정 주장이 있어야, 관측 문장은 모든 주장이 관측이어야 맞다. 주장이 없으면 틀리다."""
    if not kinds:
        return False
    return "decision" in kinds if gold == "decision" else all(kind == "observation" for kind in kinds)


def measure_kinds(llm, items: list[dict], workers: int) -> dict:
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda item: extract_claims(llm, item["note"]), items))
    hits = {"decision": [0, 0], "observation": [0, 0]}
    wrong = []
    for item, result in zip(items, results):
        kinds = [claim.data["kind"] for claim in result.stored]
        right = result.error is None and kind_correct(item["gold"], kinds)
        hits[item["gold"]][0] += right
        hits[item["gold"]][1] += 1
        if not right:
            wrong.append({"id": item["id"], "gold": item["gold"], "note": item["note"][:200], "kinds": kinds, "error": result.error})
    return {"decision": rate(*hits["decision"]), "observation": rate(*hits["observation"]),
            "errors": sum(result.error is not None for result in results), "wrong": wrong}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    llm = ServerLLM()
    report = {
        "split": args.split, "model": llm.model, "thinking": llm.thinking,
        "prompts": [STRUCTURE_VERSION, INTERPRET_VERSION],
        "claims": measure_claims(llm, read_jsonl(args.data / f"measeval-{args.split}.jsonl"), args.workers),
        "questions": measure_questions(llm, read_jsonl(args.data / f"wikisql-{args.split}.jsonl"), args.workers),
        "kinds": measure_kinds(llm, read_jsonl(args.data / f"kind-{args.split}.jsonl"), args.workers),
        "llm": llm.stats,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    hidden = {"misses", "wrong"}
    summary = {key: ({k: v for k, v in value.items() if k not in hidden} if isinstance(value, dict) else value)
               for key, value in report.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if not llm.stats["calls"] and not llm.stats["cache_hits"]:
        raise SystemExit("LLM 호출이 한 건도 성공하지 못했다")


if __name__ == "__main__":
    main()
