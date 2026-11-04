"""GroupMemBench(https://github.com/UCSB-NLP-Chang/GroupMemBench)에서 한 시간 안에 돌릴 작은 실험 세트를 만든다.

- knowledge_update: 정답이 어느 "결정 변경" 메시지에서 나왔는지 찾아, 그 메시지와 원래 결정 메시지,
  각각의 답장 대상(부모) 메시지를 근거로 넣는다.
- abstention: 대화에 답이 없는 질문이다. 근거는 없고 방해 메시지만 넣는다.
- 질문마다 전체 메시지 중 BM25로 가장 비슷한 메시지를 방해 메시지로 더한다(쉬운 문제가 되지 않게).

결정 변경 여부·원래 결정 연결 같은 생성 라벨은 세트를 만들 때만 쓰고 시스템에는 넘기지 않는다.
시스템이 보는 필드는 GroupMemBench 베이스라인이 에이전트에게 보여주는 것과 같다(PUBLIC_FIELDS).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from harness.retriever import BM25

PUBLIC_FIELDS = ("msg_node", "content", "author", "role", "_channel", "phase_name", "topic", "timestamp", "reply_to")
_STOP = {"the", "a", "an", "to", "and", "of", "for", "in", "on", "with", "that", "is", "it", "we", "this",
         "be", "as", "now", "so", "but", "or", "are", "at", "by", "if", "not", "can", "i", "you"}


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _content_words(text: str) -> set[str]:
    return set(words(text)) - _STOP


def load_domain(gmb: Path, domain: str) -> tuple[list[dict], dict[str, list[dict]]]:
    data = json.loads((gmb / "data" / "final" / domain /
                       f"synthetic_domain_channels_rolevariants_{domain}.json").read_text(encoding="utf-8"))
    msgs = [dict(m, _channel=ch) for ch, v in data.items() for m in v]
    msgs.sort(key=lambda m: (m["_channel"], m["timestamp"], m["msg_node"]))  # GroupMemBench 로더와 같은 순서
    qs = {}
    for qt in ("knowledge_update", "abstention"):
        path = gmb / "questions" / domain / f"{qt}.jsonl"
        qs[qt] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return msgs, qs


def public(m: dict) -> dict:
    return {k: m.get(k) for k in PUBLIC_FIELDS}


def build(gmb: str | Path, domain: str = "Finance", n_ku: int = 8, n_abs: int = 8, negatives: int = 6) -> dict:
    gmb = Path(gmb)
    msgs, qs = load_domain(gmb, domain)
    by_id = {m["msg_node"]: m for m in msgs}
    bm25 = BM25([m["content"] for m in msgs], tokenizer=words)

    def top(query: str, k: int, exclude: set[str]) -> list[str]:
        scores = bm25.scores(query)
        order = sorted(range(len(msgs)), key=lambda i: -scores[i])
        out = []
        for i in order:
            mid = msgs[i]["msg_node"]
            if mid not in exclude:
                out.append(mid)
            if len(out) == k:
                break
        return out

    changed = [m for m in msgs if m.get("decision_type") == "changed"]
    matched = []
    for q in qs["knowledge_update"]:
        ans = _content_words(q["answer"])
        best = max(changed, key=lambda m: len(ans & _content_words(m["content"])) / max(1, len(ans)))
        score = len(ans & _content_words(best["content"])) / max(1, len(ans))
        label = best.get("decision_label") or {}
        if score >= 0.6 and label.get("linked_to_msg") in by_id:
            matched.append((score, q, best["msg_node"], label["linked_to_msg"]))
    matched.sort(key=lambda t: -t[0])

    keep: dict[str, None] = {}  # 순서를 지키는 집합
    questions, gold = [], {}
    for _, q, new_id, old_id in matched[:n_ku]:
        evidence = [new_id, old_id] + [by_id[x]["reply_to"] for x in (new_id, old_id)
                                        if by_id[x].get("reply_to") in by_id]
        for mid in evidence + top(q["question"], negatives, set(evidence)):
            keep[mid] = None
        questions.append(dict(q, qtype="knowledge_update"))
        gold[q["id"]] = {"current": new_id, "stale": old_id}
    for q in qs["abstention"][:n_abs]:
        for mid in top(q["question"], negatives, set()):
            keep[mid] = None
        questions.append(dict(q, qtype="abstention"))
        gold[q["id"]] = {}
    subset = sorted((by_id[mid] for mid in keep), key=lambda m: (m["_channel"], m["timestamp"], m["msg_node"]))
    return {"domain": domain, "messages": [public(m) for m in subset], "questions": questions, "gold": gold,
            "source": "GroupMemBench " + domain}
