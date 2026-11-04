"""GroupMemBench 작은 세트 비교 실험. 도메인별로 실행하고, groupmem.summarize로 합쳐서 통계를 낸다.

    python -m groupmem.run --gmb <GroupMemBench 폴더> --domain Finance --systems bm25,harness,harness-no_scope,harness-no_judge
    python -m groupmem.run --gmb <GroupMemBench 폴더> --domain Finance --systems graphiti
    python -m groupmem.summarize

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
    if name.startswith("harness"):
        return systems.HarnessGMB(scope="no_scope" not in name, judge="no_judge" not in name)
    if name in ("graphiti", "graphiti_tuned"):
        return systems.GraphitiGMB(tuned=name == "graphiti_tuned")
    raise ValueError(f"알 수 없는 시스템: {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gmb", required=True, help="GroupMemBench를 받은 폴더")
    ap.add_argument("--domain", default="Finance")
    ap.add_argument("--n-ku", type=int, default=31, help="knowledge_update 문항 수(근거 연결 가능한 만큼까지)")
    ap.add_argument("--n-abs", type=int, default=29, help="abstention 문항 수")
    ap.add_argument("--negatives", type=int, default=6, help="질문당 방해 메시지 수")
    ap.add_argument("--systems", default="bm25,harness")
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()

    gmb = Path(args.gmb)
    agent_system = (gmb / "prompts" / "hipporag_agent_system.txt").read_text(encoding="utf-8").strip()
    judge_system = (gmb / "prompts" / "hipporag_judge_system.txt").read_text(encoding="utf-8").strip()
    subset = build(gmb, args.domain, args.n_ku, args.n_abs, args.negatives)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / f"gmb_{args.domain}_subset.json").write_text(json.dumps(subset, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"작은 세트: {args.domain} 메시지 {len(subset['messages'])}개, 질문 {len(subset['questions'])}개 "
          f"(답변·판정 모델 {llm.ANSWER_MODEL}, 근거 판정 모델 {llm.SMALL_MODEL})", flush=True)

    for name in args.systems.split(","):
        system = build_system(name)
        system.ingest(subset["messages"])
        rows = []
        for q in subset["questions"]:
            asker = q.get("asking_user_id", "")
            calls_before = llm.stats["calls"] + llm.stats["cache_hits"]
            passages, ids = system.retrieve(q["question"], asker)
            pre_calls = llm.stats["calls"] + llm.stats["cache_hits"] - calls_before
            passages_text = "\n\n".join(f"[{i}] {p}" for i, p in enumerate(passages, start=1))
            agent_user = ((f"Asking user: {asker}\n\n" if asker else "") + f"Question:\n{q['question']}\n\n"
                          f"Retrieved passages:\n{passages_text}\n\nAnswer the question using the retrieved passages.")
            answer = final_line(llm.chat_text(llm.ANSWER_MODEL, agent_system, agent_user, 2000))
            judge_user = f"Question:\n{q['question']}\n\nGold Answer:\n{q['answer']}\n\nAgent Answer:\n{answer}\n"
            ok = judged_correct(llm.chat_text(llm.ANSWER_MODEL, judge_system, judge_user, 1000))
            gold = subset["gold"][q["id"]]
            row = {"domain": args.domain, "system": name, "id": q["id"], "qtype": q["qtype"],
                   "question": q["question"], "gold": q["answer"], "answer": answer, "correct": ok,
                   "retrieved_ids": ids, "context_chars": len(passages_text), "llm_calls_before_answer": pre_calls,
                   "current_retrieved": gold.get("current") in ids if gold else None,
                   "stale_retrieved": gold.get("stale") in ids if gold else None}
            j = getattr(system, "last_judgment", None)
            if j is not None:  # 하네스 근거 판정의 품질(생성 라벨과 대조, 채점용으로만 사용)
                row["judge"] = j.model_dump()
                row["judge_answerable_ok"] = j.answerable == (q["qtype"] != "abstention")
                if gold:
                    row["judge_current_ok"] = gold["current"] in j.current_ids
                    row["judge_stale_marked"] = gold["stale"] in j.superseded_ids
            rows.append(row)
            print(f"[{args.domain}/{name}] {q['id']}: {'O' if ok else 'X'}  {answer[:90]}", flush=True)
        with open(out / f"gmb_{args.domain}_{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n_ok = sum(bool(r["correct"]) for r in rows)
        print(f"[{args.domain}/{name}] 정답 {n_ok}/{len(rows)}, 입력 시간 {getattr(system, 'ingest_minutes', 0.0):.1f}분",
              flush=True)
        if hasattr(system, "ingest_minutes"):
            (out / f"gmb_{args.domain}_{name}.ingest.json").write_text(
                json.dumps({"minutes": system.ingest_minutes, "messages": len(subset["messages"])}), encoding="utf-8")
        if hasattr(system, "close"):
            system.close()
    print(f"\nLLM 호출 {llm.stats['calls']}회, 캐시 재사용 {llm.stats['cache_hits']}회. "
          f"모든 도메인이 끝나면: python -m groupmem.summarize")


if __name__ == "__main__":
    main()
