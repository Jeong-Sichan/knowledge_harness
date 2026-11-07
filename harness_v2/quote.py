"""D3 인용 검증. 규칙만 쓰고 LLM은 쓰지 않는다.

- 인용은 원문에 글자 그대로 있어야 한다. 공백·줄바꿈 차이만 허용한다.
- 위치(start/end)는 서버가 찾아 붙인다.
- 틀리면 원문에서 가장 비슷한 구간을 같이 돌려준다.
- 300자 이하 원문은 원문 전체를 인용으로 처리한다.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

AUTO_QUOTE_MAX = 300
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class QuoteResult:
    ok: bool
    start: int | None = None
    end: int | None = None
    nearest: str | None = None


def _collapse(text: str) -> tuple[str, list[int]]:
    """공백 묶음을 한 칸으로 줄이고, 줄인 글자마다 원문 위치를 기억한다."""
    chars: list[str] = []
    pos: list[int] = []
    in_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_space:
                chars.append(" ")
                pos.append(i)
            in_space = True
        else:
            chars.append(ch)
            pos.append(i)
            in_space = False
    return "".join(chars), pos


def nearest_span(source: str, quote: str) -> str:
    """인용과 가장 비슷한 원문 구간을 찾는다. 재시도 안내용이라 판정에는 쓰지 않는다."""
    norm_quote = _WS.sub(" ", quote).strip()
    if not norm_quote or not source.strip():
        return ""
    flat, _ = _collapse(source)
    size = len(norm_quote)
    step = max(1, size // 4)
    best, best_score = "", -1.0
    for start in range(0, max(1, len(flat) - size + 1), step):
        window = flat[start:start + size]
        matcher = difflib.SequenceMatcher(None, norm_quote, window, autojunk=False)
        if matcher.quick_ratio() <= best_score:
            continue
        score = matcher.ratio()
        if score > best_score:
            best, best_score = window, score
    return best.strip()


def find_quote(source: str, quote: str) -> QuoteResult:
    """인용 위치를 찾는다. 없으면 ok=False와 가장 비슷한 구간을 돌려준다."""
    norm_quote = _WS.sub(" ", quote).strip()
    if not norm_quote:
        return QuoteResult(ok=False, nearest="")
    flat, pos = _collapse(source)
    at = flat.find(norm_quote)
    if at < 0:
        return QuoteResult(ok=False, nearest=nearest_span(source, quote))
    return QuoteResult(ok=True, start=pos[at], end=pos[at + len(norm_quote) - 1] + 1)


def auto_quote(source: str) -> str | None:
    """300자 이하 원문이면 원문 전체가 인용이다. 더 길면 None."""
    return source if len(source) <= AUTO_QUOTE_MAX else None
