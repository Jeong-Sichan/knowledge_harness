"""리트리버 모듈(Retriever): 팀 기록에서 질문과 관련된 기록을 찾는다.

질문이 구조화되어 topic이 있으면 topic으로 바로 찾고, 없으면 BM25로 찾는다.
외부 의존성 없이 돌도록 BM25를 직접 구현했다(한국어는 공백 + 문자 2-gram 토큰).
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .schema import Query, Record


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[0-9A-Za-z_.]+|[가-힣]+", text.lower())
    tokens: list[str] = []
    for w in words:
        tokens.append(w)
        if re.match(r"[가-힣]", w) and len(w) > 2:
            tokens.extend(w[i:i + 2] for i in range(len(w) - 1))
    return tokens


def record_text(r: Record) -> str:
    cond = " ".join(f"{k} {v}" for k, v in r.conditions.items())
    return f"{r.text} {r.topic.replace('_', ' ')} {r.value} {cond}"


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.toks = [tokenize(d) for d in docs]
        self.avgdl = sum(map(len, self.toks)) / max(1, len(self.toks))
        df = Counter(t for doc in self.toks for t in set(doc))
        n = len(self.toks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for doc in self.toks:
            tf = Counter(doc)
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(doc) / self.avgdl))
            out.append(s)
        return out


def bm25_top_k(records: list[Record], question: str, k: int) -> list[Record]:
    if not records:
        return []
    scores = BM25([record_text(r) for r in records]).scores(question)
    ranked = sorted(zip(scores, records), key=lambda x: -x[0])
    return [r for s, r in ranked[:k] if s > 0]


class Retriever:
    def __init__(self, k: int = 10):
        self.k = k

    def retrieve(self, records: list[Record], q: Query) -> list[Record]:
        if q.topic:
            return [r for r in records if r.topic == q.topic]
        return bm25_top_k(records, q.question, self.k)
