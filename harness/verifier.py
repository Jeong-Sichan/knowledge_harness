"""인용 검증 모듈(Verifier): 인용 구간이 원문의 해당 버전에 실제로 있는지 판단한다.

1단계는 규칙 기반(정확 일치 → 유사도)으로 싸게 거르고, 애매한 경우만 큰 모델에 넘기는 구조다.
같은 근거 키는 한 번만 검증하도록 캐시한다. 재인용이 많을수록 캐시 히트가 난다.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from .schema import Evidence

# 애매 구간: 이 사이의 유사도면 LLM 판정으로 넘긴다
FUZZY_ACCEPT = 0.92
FUZZY_AMBIGUOUS = 0.75
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _norm(s: str) -> str:
    return " ".join(s.split())


class SourceStore:
    """원문 저장소. data/sources/<source>.md 를 rev 1로 읽는다(버전 관리는 TODO)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._cache: dict[tuple[str, int], str] = {}

    def get(self, source: str, rev: int) -> str | None:
        key = (source, rev)
        if key not in self._cache:
            path = self.root / f"{source}.md"
            self._cache[key] = path.read_text(encoding="utf-8") if path.exists() else None
        return self._cache[key]


class CitationVerifier:
    def __init__(self, sources: SourceStore,
                 llm_judge: Callable[[str, str], bool] | None = None):
        self.sources = sources
        self.llm_judge = llm_judge  # (원문, 인용) -> 맞는 인용인가. 큰 모델 자리.
        self._cache: dict[tuple, bool] = {}
        self.stats = {"calls": 0, "cache_hits": 0, "llm_calls": 0}

    def verify(self, ev: Evidence) -> bool:
        self.stats["calls"] += 1
        if ev.key in self._cache:
            self.stats["cache_hits"] += 1
            return self._cache[ev.key]
        result = self._verify_uncached(ev)
        self._cache[ev.key] = result
        return result

    def _verify_uncached(self, ev: Evidence) -> bool:
        text = self.sources.get(ev.source, ev.rev)
        if text is None:
            return False
        quote, body = _norm(ev.quote), _norm(text)
        if quote in body:
            return True
        best, window = _best_window(quote, body)
        # 숫자 하나만 바뀐 인용(0.05 → 0.1)은 유사도가 높아도 틀린 인용이다
        if _NUM.findall(quote) != _NUM.findall(window):
            return False
        if best >= FUZZY_ACCEPT:
            return True
        if best >= FUZZY_AMBIGUOUS and self.llm_judge is not None:
            self.stats["llm_calls"] += 1
            return self.llm_judge(text, ev.quote)
        return False


def _best_window(quote: str, body: str) -> tuple[float, str]:
    """원문에서 인용 길이만큼의 창을 밀며 가장 비슷한 구간과 그 유사도."""
    n = len(quote)
    if n == 0 or not body:
        return 0.0, ""
    best, best_window = 0.0, ""
    for i in range(0, max(1, len(body) - n + 1)):
        window = body[i:i + n]
        ratio = SequenceMatcher(None, quote, window).ratio()
        if ratio > best:
            best, best_window = ratio, window
    return best, best_window
