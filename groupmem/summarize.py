"""results/gmb_<도메인>_<시스템>.jsonl을 모아 시스템별 정답률, 95% 신뢰구간, bm25 대비 맞비교 검정을 낸다.

    python -m groupmem.summarize                 # results/ 폴더
    python -m groupmem.summarize --out results

- 신뢰구간: 문항을 다시 뽑는 부트스트랩 2000회(시드 고정)
- 맞비교: 같은 문항에서 bm25와 결과가 갈린 문항만 세는 McNemar 정확 검정(양측)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["bm25", "harness", "harness-no_scope", "harness-no_judge", "graphiti", "graphiti_tuned"]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ci95(values: list[bool], reps: int = 2000) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(0)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def mcnemar_p(b: int, c: int) -> float:
    """b: 기준만 맞힘, c: 비교 대상만 맞힘. 이항 정확 검정 양측 p."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load(out: Path) -> dict[str, list[dict]]:
    rows = defaultdict(list)
    for path in sorted(out.glob("gmb_*_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["system"]].append(r)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "results"))
    out = Path(ap.parse_args().out)
    rows = load(out)
    systems = [s for s in ORDER if s in rows] + sorted(s for s in rows if s not in ORDER)
    domains = sorted({r["domain"] for rs in rows.values() for r in rs})
    print(f"도메인: {', '.join(domains)}")

    def acc(rs):
        return sum(bool(r["correct"]) for r in rs) / max(1, len(rs))

    print("\n| system | 문항 | knowledge_update | abstention | 전체 (95% CI) | bm25 대비 p | 현재 결정 검색률 | 질문당 맥락 글자 | 답변 전 LLM 호출/문항 | 입력 시간(분) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    base = {(r["domain"], r["id"]): bool(r["correct"]) for r in rows.get("bm25", [])}
    for s in systems:
        rs = rows[s]
        ku = [r for r in rs if r["qtype"] == "knowledge_update"]
        ab = [r for r in rs if r["qtype"] == "abstention"]
        lo, hi = ci95([bool(r["correct"]) for r in rs])
        if s != "bm25" and base:
            b = sum(1 for r in rs if base.get((r["domain"], r["id"])) and not r["correct"])
            c = sum(1 for r in rs if base.get((r["domain"], r["id"])) is False and r["correct"])
            p = f"{mcnemar_p(b, c):.3f} (bm25만 {b} / 이쪽만 {c})"
        else:
            p = "-"
        rec = sum(bool(r["current_retrieved"]) for r in ku) / max(1, len(ku))
        chars = sum(r["context_chars"] for r in rs) / max(1, len(rs))
        calls = sum(r.get("llm_calls_before_answer", 0) for r in rs) / max(1, len(rs))
        mins = 0.0
        for d in domains:
            f = out / f"gmb_{d}_{s}.ingest.json"
            if f.exists():
                mins += json.loads(f.read_text(encoding="utf-8"))["minutes"]
        print(f"| {s} | {len(rs)} | {acc(ku):.2f} ({sum(bool(r['correct']) for r in ku)}/{len(ku)}) | "
              f"{acc(ab):.2f} ({sum(bool(r['correct']) for r in ab)}/{len(ab)}) | {acc(rs):.2f} ({lo:.2f}–{hi:.2f}) | {p} | "
              f"{rec:.2f} | {chars:.0f} | {calls:.1f} | {mins:.1f} |")

    for s in systems:
        js = [r for r in rows[s] if "judge" in r]
        if not js:
            continue
        ku = [r for r in js if r["qtype"] == "knowledge_update"]
        print(f"\n[{s}] 근거 판정 품질: 답할 수 있는지 판정 정확도 "
              f"{sum(r['judge_answerable_ok'] for r in js)}/{len(js)} "
              f"(knowledge_update {sum(r['judge_answerable_ok'] for r in ku)}/{len(ku)}, "
              f"abstention {sum(r['judge_answerable_ok'] for r in js if r['qtype'] == 'abstention')}/{len(js) - len(ku)}), "
              f"현재 결정 지목 {sum(r['judge_current_ok'] for r in ku)}/{len(ku)}, "
              f"이전 결정을 대체됨으로 표시 {sum(r['judge_stale_marked'] for r in ku)}/{len(ku)}")


if __name__ == "__main__":
    main()
