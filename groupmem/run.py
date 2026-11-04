"""GroupMemBench 작은 세트 비교 실험.

    python -m groupmem.run --gmb <GroupMemBench 폴더> --systems bm25,harness
    python -m groupmem.run --gmb <GroupMemBench 폴더> --systems graphiti          # 터미널 2
    python -m groupmem.run --gmb <GroupMemBench 폴더> --systems graphiti_tuned    # 터미널 3

답변과 판정은 GroupMemBench의 프롬프트(prompts/hipporag_agent_system.txt, hipporag_judge_system.txt)와
질의·근거 표시 형식을 그대로 쓴다. 모델은 모든 시스템에 같다(HARNESS_ANSWER_MODEL, 기본 gpt-6-luna).
원본과 다른 점: 최신 추론 모델이 temperature를 받지 않아 빼고, 추론 토큰을 고려해 출력 한도를 2000/1000으로 늘렸다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import llm

from .subset import build

ROOT = Path(__file__).resolve().parent.parent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def final_line(text: str) -> str:
    """GroupMemBench eval_lib.extract_final과 같은 규칙."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.lower().startswith(("final:", "final answer:")):
            return ln.split(":", 1)[1].strip()
    return lines[-1] if lines else ""


def judged_correct(judge_text: str) -> bool | None:
    f = final_line(judge_text).lower()
    if "incorrect" in f or "wrong" in f or "not correct" in f:
        return False
    return True if "correct" in f else None


def build_system(name: str):
    from . import systems
    if name == "bm25":
        return systems.BM25System()
    if name == "harness":
        return systems.HarnessGMB()
    if name in ("graphiti", "graphiti_tuned"):
        return systems.GraphitiGMB(tuned=name == "graphiti_tuned")
    raise ValueError(f"알 수 없는 시스템: {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gmb", required=True, help="GroupMemBench를 받은 폴더")
    ap.add_argument("--domain", default="Finance")
    ap.add_argument("--n-ku", type=int, default=8)
    ap.add_argument("--n-abs", type=int, default=8)
    ap.add_argument("--negatives", type=int, default=6)
    ap.add_argument("--systems", default="bm25,harness")
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()

    gmb = Path(args.gmb)
    agent_system = (gmb / "prompts" / "hipporag_agent_system.txt").read_text(encoding="utf-8").strip()
    judge_system = (gmb / "prompts" / "hipporag_judge_system.txt").read_text(encoding="utf-8").strip()
    subset = build(gmb, args.domain, args.n_ku, args.n_abs, args.negatives)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "gmb_subset.json").write_text(json.dumps(subset, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"작은 세트: {args.domain} 메시지 {len(subset['messages'])}개, 질문 {len(subset['questions'])}개 "
          f"(답변·판정 모델 {llm.ANSWER_MODEL})")

    table = []
    for name in args.systems.split(","):
        system = build_system(name)
        system.ingest(subset["messages"])
        rows = []
        for q in subset["questions"]:
            passages, ids = system.retrieve(q["question"], q.get("asking_user_id", ""))
            asker = q.get("asking_user_id", "")
            passages_text = "\n\n".join(f"[{i}] {p}" for i, p in enumerate(passages, start=1))
            agent_user = ((f"Asking user: {asker}\n\n" if asker else "") + f"Question:\n{q['question']}\n\n"
                          f"Retrieved passages:\n{passages_text}\n\nAnswer the question using the retrieved passages.")
            answer = final_line(llm.chat_text(llm.ANSWER_MODEL, agent_system, agent_user, 2000))
            judge_user = f"Question:\n{q['question']}\n\nGold Answer:\n{q['answer']}\n\nAgent Answer:\n{answer}\n"
            ok = judged_correct(llm.chat_text(llm.ANSWER_MODEL, judge_system, judge_user, 1000))
            gold = subset["gold"][q["id"]]
            rows.append({"id": q["id"], "qtype": q["qtype"], "question": q["question"], "gold": q["answer"],
                         "answer": answer, "correct": ok, "retrieved_ids": ids,
                         "current_retrieved": gold.get("current") in ids if gold else None,
                         "stale_retrieved": gold.get("stale") in ids if gold else None,
                         "context_chars": len(passages_text)})
            print(f"[{name}] {q['id']}: {'O' if ok else 'X'}  {answer[:90]}", flush=True)
        with open(out / f"gmb_{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        acc = lambda qt: sum(bool(r["correct"]) for r in rows if r["qtype"] == qt) / max(1, sum(r["qtype"] == qt for r in rows))  # noqa: E731
        ku = [r for r in rows if r["qtype"] == "knowledge_update"]
        table.append((name, acc("knowledge_update"), acc("abstention"), sum(bool(r["correct"]) for r in rows) / len(rows),
                      sum(r["current_retrieved"] for r in ku) / max(1, len(ku)),
                      sum(r["context_chars"] for r in rows) / len(rows), getattr(system, "ingest_minutes", 0.0)))
        if hasattr(system, "close"):
            system.close()

    print(f"\nLLM 호출 {llm.stats['calls']}회, 캐시 재사용 {llm.stats['cache_hits']}회")
    print("\n| system | knowledge_update | abstention | 전체 | 최신 근거 검색률 | 질문당 맥락 글자 수 | 입력 시간(분) |")
    print("|---|---|---|---|---|---|---|")
    for name, ku, ab, allacc, rec, chars, mins in table:
        print(f"| {name} | {ku:.2f} | {ab:.2f} | {allacc:.2f} | {rec:.2f} | {chars:.0f} | {mins:.1f} |")


if __name__ == "__main__":
    main()
