"""공개 데이터를 1층 측정용 JSONL로 바꾼다. 원본과 결과 파일은 git에 올리지 않는다.

- MeasEval: 주장 뽑기. trial이 개발용, eval이 시험용.
- WikiSQL: 질문 해석. dev가 개발용, test가 시험용. `=` 조건만 쓴다(D5).
- Hibernate 결정 + MeasEval 수치 문장: 관측/결정 분류.

실행: python -m eval.public_data --measeval <폴더> --wikisql <폴더> --hibernate <decisions.xlsx> --out <폴더>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import zipfile
from pathlib import Path

LIMITS = {"dev": {"wikisql": 50, "kind": 50}, "test": {"wikisql": 200, "kind": 150}}
MEASEVAL_DIRS = {"dev": ("trial", "txt"), "test": ("eval", "text")}
WIKISQL_FILES = {"dev": "dev", "test": "test"}
MIN_SENTENCE, MAX_SENTENCE = 40, 300


def load_measeval(root: Path, split: str) -> list[dict]:
    """문단마다 정답 묶음(수치, 측정 대상, 속성, 한정 조건)과 수치 위치를 모은다."""
    folder, text_dir = MEASEVAL_DIRS[split]
    notes = []
    for tsv in sorted((root / "data" / folder / "tsv").glob("*.tsv")):
        text_path = root / "data" / folder / text_dir / f"{tsv.stem}.txt"
        if not text_path.exists():
            continue
        sets: dict[str, dict] = {}
        with open(tsv, encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file, delimiter="\t"):
                item = sets.setdefault(row["annotSet"], {"quantity": None, "entity": None, "property": None,
                                                         "qualifier": None, "start": None})
                key = {"Quantity": "quantity", "MeasuredEntity": "entity", "MeasuredProperty": "property",
                       "Qualifier": "qualifier"}[row["annotType"]]
                item[key] = row["text"]
                if key == "quantity":
                    item["start"] = int(row["startOffset"])
        gold = [item for item in sets.values() if item["quantity"]]
        if gold:
            notes.append({"id": f"measeval-{tsv.stem}", "note": text_path.read_text(encoding="utf-8"), "gold": gold})
    return notes


def sentence_at(text: str, position: int) -> str | None:
    """위치를 포함한 문장을 돌려준다."""
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+", text):
        if match.start() >= position:
            return text[start:match.start()].strip()
        start = match.end()
    return text[start:].strip()


def observation_sentences(notes: list[dict]) -> list[dict]:
    seen, items = set(), []
    for note in notes:
        for item in note["gold"]:
            sentence = sentence_at(note["note"], item["start"])
            if sentence and MIN_SENTENCE <= len(sentence) <= MAX_SENTENCE and sentence not in seen:
                seen.add(sentence)
                items.append({"id": f"obs-{hashlib.sha256(sentence.encode()).hexdigest()[:12]}", "note": sentence,
                              "gold": "observation"})
    return items


def load_decisions(path: Path) -> list[dict]:
    """xlsx의 문장·종류 열을 읽는다. 표준 라이브러리로 파일 구조만 읽는다."""
    with zipfile.ZipFile(path) as book:
        shared = book.read("xl/sharedStrings.xml").decode("utf-8")
        sheet = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
    strings = ["".join(re.findall(r"<t[^>]*>([^<]*)</t>", item)) for item in re.findall(r"<si>(.*?)</si>", shared, re.S)]
    items = []
    for row in re.findall(r"<row [^>]*>(.*?)</row>", sheet, re.S):
        cells = [strings[int(value)] for value in re.findall(r'<c [^>]*t="s"[^>]*><v>(\d+)</v>', row)]
        if len(cells) >= 2 and cells[1].strip().lower().endswith("decision"):
            text = re.sub(r"\s+", " ", unescape_xml(cells[0])).strip()
            items.append({"id": f"dec-{hashlib.sha256(text.encode()).hexdigest()[:12]}", "note": text, "gold": "decision"})
    return items


def unescape_xml(text: str) -> str:
    for code, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(code, char)
    return text


def load_wikisql(root: Path, split: str) -> list[dict]:
    name = WIKISQL_FILES[split]
    tables = {}
    with open(root / f"{name}.tables.jsonl", encoding="utf-8") as file:
        for line in file:
            table = json.loads(line)
            tables[table["id"]] = table["header"]
    items = []
    with open(root / f"{name}.jsonl", encoding="utf-8") as file:
        for number, line in enumerate(file):
            query = json.loads(line)
            conditions = query["sql"]["conds"]
            if not conditions or any(op != 0 for _, op, _ in conditions):
                continue
            header = tables[query["table_id"]]
            items.append({"id": f"wikisql-{name}-{number}", "question": query["question"], "topics": header,
                          "topic": header[query["sql"]["sel"]],
                          "conditions": [[header[column], str(value)] for column, _, value in conditions]})
    return items


def sample(items: list[dict], limit: int, seed: str) -> list[dict]:
    chosen = list(items)
    random.Random(seed).shuffle(chosen)
    return chosen[:limit]


def write_jsonl(path: Path, items: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as file:
        for item in items:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measeval", required=True, type=Path)
    parser.add_argument("--wikisql", required=True, type=Path)
    parser.add_argument("--hibernate", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    decisions = load_decisions(args.hibernate)
    random.Random("layer1-decisions").shuffle(decisions)
    cut = LIMITS["dev"]["kind"]
    decision_sets = {"dev": decisions[:cut], "test": decisions[cut:cut + LIMITS["test"]["kind"]]}
    for split in ("dev", "test"):
        notes = load_measeval(args.measeval, split)
        write_jsonl(args.out / f"measeval-{split}.jsonl", notes)
        questions = sample(load_wikisql(args.wikisql, split), LIMITS[split]["wikisql"], f"wikisql-{split}")
        write_jsonl(args.out / f"wikisql-{split}.jsonl", questions)
        observations = sample(observation_sentences(notes), LIMITS[split]["kind"], f"kind-{split}")
        write_jsonl(args.out / f"kind-{split}.jsonl", decision_sets[split] + observations)
        print(split, "notes", len(notes), "gold", sum(len(n["gold"]) for n in notes), "questions", len(questions),
              "decisions", len(decision_sets[split]), "observations", len(observations))


if __name__ == "__main__":
    main()
