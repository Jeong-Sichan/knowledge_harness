"""베이스라인 대비 하네스 평가.

두 가지 모드가 있다.

rule 모드 (기본, 오프라인): 하네스는 정답 구조(topic·조건)를 받고 템플릿으로 답한다. 모듈 개발·ablation용.
    python -m eval.run_eval -v

llm 모드 (공정 비교): 모든 시스템이 자유 텍스트 기록 + 질문 문장만 받고, 같은 LLM 답변기로 답한다.
하네스도 기록 구조화와 질문 파싱을 LLM으로 직접 한다. OPENAI_API_KEY 필요.
    python -m eval.run_eval --answerer llm --systems retrieval_only,full_context_llm,harness --no-ablation -v
    python -m eval.run_eval --answerer llm --systems retrieval_only,full_context_llm,harness,graphiti -v

규모 실험: --scale N 이면 조건만 다른 방해 기록 N개를 섞는다(eval/scale.py). 정답 라벨은 그대로 유효하다.
    python -m eval.run_eval --scale 300 --no-ablation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import ComposerConfig, Harness, Query, Record

from .metrics import score_query, summarize

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Windows(cp949) 터미널에서도 한글·기호 출력이 깨지거나 멈추지 않게 한다
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ABLATIONS = {
    "harness-no_conditions": {"cfg": ComposerConfig(use_conditions=False)},
    "harness-no_verifier": {"cfg": ComposerConfig(use_verifier=False)},
    "harness-no_dedup": {"cfg": ComposerConfig(use_dedup=False)},
    "harness-no_approval": {"cfg": ComposerConfig(use_approval=False)},
    "harness-no_pii": {"use_pii": False},
}


def build(name: str, answerer: str, src: Path = DATA / "sources"):
    structure = "llm" if answerer == "llm" else "gold"
    if name == "harness":
        return Harness(src, structure=structure, answerer=answerer)
    if name in ABLATIONS:
        h = Harness(src, structure=structure, answerer=answerer, **ABLATIONS[name])
        h.name = name
        return h
    if name == "retrieval_only":
        from baselines.retrieval_only import RetrievalOnly
        return RetrievalOnly(src, answerer=answerer)
    if name == "full_context_llm":
        if answerer != "llm":
            raise ValueError("full_context_llm은 --answerer llm 에서만 돈다")
        from baselines.full_context_llm import FullContextLLM
        return FullContextLLM(src)
    if name == "graphiti":
        from baselines.graphiti_baseline import GraphitiBaseline
        return GraphitiBaseline(src, answerer=answerer)
    raise ValueError(f"알 수 없는 시스템: {name}")


def report_structuring(name: str, system, gold: dict[str, dict]) -> None:
    """LLM 구조화가 정답 구조와 얼마나 맞는지. 하네스 오류가 구조화 단계에서 왔는지 가르는 데 쓴다."""
    recs = system.store.records
    cond_ok = sum(recs[i].conditions == gold[i]["conditions"] for i in recs)
    ids = sorted(recs)
    pairs = [(a, b) for k, a in enumerate(ids) for b in ids[k + 1:]]
    topic_ok = sum((gold[a]["topic"] == gold[b]["topic"]) == (recs[a].topic == recs[b].topic) for a, b in pairs)
    print(f"[{name}] 구조화 정확도: 조건 {cond_ok}/{len(ids)}, 주제 묶음(쌍 기준) {topic_ok}/{len(pairs)}")
    for i in ids:
        r = recs[i]
        mark = "" if r.conditions == gold[i]["conditions"] else "  <- 조건 다름(정답 " + str(gold[i]["conditions"]) + ")"
        print(f"      {i}: topic={r.topic} value={r.value} cond={r.conditions}{mark}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="retrieval_only,harness")
    ap.add_argument("--answerer", choices=["rule", "llm"], default="rule")
    ap.add_argument("--scale", type=int, default=0, help="섞을 방해 기록 수")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()

    src = DATA / "sources"
    if args.scale:
        from .scale import build_scaled_dataset
        raw_records, src = build_scaled_dataset(args.scale, args.seed)
        print(f"규모 실험: 기록 {len(raw_records)}개 (방해 기록 {args.scale}개, seed {args.seed})")
    else:
        raw_records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    gold_queries = json.loads((DATA / "queries.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw_records}

    names = args.systems.split(",")
    if not args.no_ablation and "harness" in names:
        names += list(ABLATIONS)

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    table = []
    llm_mode = args.answerer == "llm"
    for name in names:
        system = build(name, args.answerer, src)
        # '_'로 시작하는 정답 라벨은 Record.from_dict가 버린다
        system.ingest([Record.from_dict(r) for r in raw_records])
        if llm_mode and hasattr(system, "store"):
            report_structuring(name, system, by_id)
        scores, details = [], []
        for g in gold_queries:
            # llm 모드에서는 모든 시스템이 질문 문장만 받는다(정답 topic·조건은 채점에만 쓴다)
            q = Query(g["id"], g["question"]) if llm_mode else Query.from_dict(g)
            resp = system.ask(q)
            s = score_query(g, resp, by_id)
            scores.append(s)
            details.append({"query": g["id"], "question": g["question"], "expected": g["expected_status"],
                            "status": resp.status, "supporting": resp.supporting_ids,
                            "team_facts": resp.team_fact_ids, "independent": resp.independent_evidence,
                            "answer": resp.answer, "notes": resp.notes, "exposed": resp.exposed,
                            "condition_match": s.condition_match})
            if args.verbose:
                mark = "O" if s.condition_match else "X"
                print(f"[{name}] {g['id']} {mark} {resp.status:<16} {resp.answer}")
                for n in resp.notes:
                    print(f"      - {n}")
        summary = summarize(scores)
        table.append((name, summary))
        suffix = ("-llm" if llm_mode else "") + (f"-scale{args.scale}" if args.scale else "")
        (out_dir / f"{name}{suffix}.json").write_text(
            json.dumps({"summary": summary, "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")
        if hasattr(system, "verifier"):
            print(f"[{name}] 인용 검증 캐시: {system.verifier.stats}")
        if getattr(system, "pii_guard", None) is not None:
            print(f"[{name}] PII 차단: {system.pii_guard.stats}")
        if hasattr(system, "invalidated_facts"):
            inv = system.invalidated_facts()
            print(f"[{name}] Graphiti가 무효 처리한 사실 {len(inv)}개 (조건이 다른데 무효화됐는지 확인할 것)")
            for fact, when in inv:
                print(f"      - {fact}  (무효 시점 {when})")
        if hasattr(system, "close"):
            system.close()

    if llm_mode:
        from harness import llm
        print(f"\nLLM 호출 {llm.stats['calls']}회, 캐시 재사용 {llm.stats['cache_hits']}회 "
              f"(답변 모델 {llm.ANSWER_MODEL}, 앞단 모델 {llm.SMALL_MODEL})")
    cols = ["condition_match", "status_acc", "overgeneralization", "irrelevant_used", "false_consensus",
            "bad_citation_used", "evidence_error", "pii_in_context", "pii_in_answer", "context_chars"]
    print("\n| system | " + " | ".join(cols) + " |")
    print("|---|" + "---|" * len(cols))
    for name, s in table:
        print(f"| {name} | " + " | ".join(f"{s[c]:.0f}" if c == "context_chars" else f"{s[c]:.2f}"
                                          for c in cols) + " |")
    print("\n(condition_match·status_acc는 높을수록, 나머지는 낮을수록 좋음)")


if __name__ == "__main__":
    main()
