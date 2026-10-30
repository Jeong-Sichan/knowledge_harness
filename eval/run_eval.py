"""베이스라인 대비 하네스 평가.

    python -m eval.run_eval                       # 오프라인: 하네스 + 약한 베이스라인 + ablation
    python -m eval.run_eval --systems harness,full_context_llm   # API 키 필요
    python -m eval.run_eval --systems harness,graphiti           # Neo4j + graphiti-core 필요
    python -m eval.run_eval -v                    # 질문별 답변까지 출력
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness import ComposerConfig, Harness, Query, Record

from .metrics import score_query, summarize

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

ABLATIONS = {
    "harness-no_conditions": {"cfg": ComposerConfig(use_conditions=False)},
    "harness-no_verifier": {"cfg": ComposerConfig(use_verifier=False)},
    "harness-no_dedup": {"cfg": ComposerConfig(use_dedup=False)},
    "harness-no_approval": {"cfg": ComposerConfig(use_approval=False)},
    "harness-no_pii": {"use_pii": False},
}


def build(name: str):
    if name == "harness":
        return Harness(DATA / "sources")
    if name in ABLATIONS:
        h = Harness(DATA / "sources", **ABLATIONS[name])
        h.name = name
        return h
    if name == "retrieval_only":
        from baselines.retrieval_only import RetrievalOnly
        return RetrievalOnly()
    if name == "full_context_llm":
        from baselines.full_context_llm import FullContextLLM
        return FullContextLLM()
    if name == "graphiti":
        from baselines.graphiti_baseline import GraphitiBaseline
        return GraphitiBaseline()
    raise ValueError(f"알 수 없는 시스템: {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="retrieval_only,harness")
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()

    raw_records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    gold_queries = json.loads((DATA / "queries.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw_records}

    names = args.systems.split(",")
    if not args.no_ablation and "harness" in names:
        names += list(ABLATIONS)

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    table = []
    for name in names:
        system = build(name)
        # '_'로 시작하는 정답 라벨은 Record.from_dict가 버린다
        system.ingest([Record.from_dict(r) for r in raw_records])
        scores, details = [], []
        for g in gold_queries:
            resp = system.ask(Query.from_dict(g))
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
        (out_dir / f"{name}.json").write_text(
            json.dumps({"summary": summary, "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")
        if hasattr(system, "verifier"):
            print(f"[{name}] 인용 검증 캐시: {system.verifier.stats}")
        if getattr(system, "pii_guard", None) is not None:
            print(f"[{name}] PII 차단: {system.pii_guard.stats}")
        if hasattr(system, "close"):
            system.close()

    cols = ["condition_match", "status_acc", "overgeneralization", "false_consensus",
            "bad_citation_used", "evidence_error", "pii_leak"]
    print("\n| system | " + " | ".join(cols) + " |")
    print("|---|" + "---|" * len(cols))
    for name, s in table:
        print(f"| {name} | " + " | ".join(f"{s[c]:.2f}" for c in cols) + " |")
    print("\n(condition_match·status_acc는 높을수록, 나머지는 낮을수록 좋음)")


if __name__ == "__main__":
    main()
