"""D13 `submit_note`의 흐름. 정규식 → 원문 저장 → 주장 추출 → 관계 계산. Git push는 아직 없다."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from harness.pii import PIIGuard

from .model import Claim, Evidence, Source
from .relations import NONE, relation
from .store import Store
from .structure import PROMPT_VERSION, ExtractedClaim, extract_claims, normalize_name

CHUNK_CHARS = 6000
TOPICS_ALL_UNDER = 100
TOPICS_SHOWN = 30


@dataclass
class SubmitResult:
    source: Source
    is_new: bool
    masked: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    relations: list[tuple[str, str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def split_note(text: str, limit: int = CHUNK_CHARS) -> list[tuple[int, str]]:
    """긴 글을 (시작 위치, 조각)으로 나눈다. 빈 줄, 줄바꿈 순서로 자를 곳을 찾는다."""
    chunks, start = [], 0
    while len(text) - start > limit:
        window = text[start:start + limit]
        cut = next((window.rfind(mark) + len(mark) for mark in ("\n\n", "\n") if window.rfind(mark) > 0), limit)
        chunks.append((start, text[start:start + cut]))
        start += cut
    chunks.append((start, text[start:]))
    return chunks


def shown_names(text: str, names: list[str], limit: int = TOPICS_SHOWN) -> list[str]:
    """D14 ④ 이름이 100개를 넘으면 글과 단어가 많이 겹치는 것만 보여준다."""
    if len(names) <= TOPICS_ALL_UNDER:
        return names
    words = set(re.findall(r"\w+", text.lower()))
    return sorted(names, key=lambda name: (-len(words & set(name.split("_"))), name))[:limit]


def to_claim(item: ExtractedClaim, offset: int, source: Source, seen: tuple[str, ...], model: str) -> Claim:
    data = item.data
    evidence = Evidence(source.doc, item.start + offset, item.end + offset, data["quote"])
    return Claim("", data["kind"], data["topic"], data["value"], source.author,
                 {normalize_name(pair["key"]): pair["value"] for pair in data["conditions"]},
                 (evidence,), seen=seen, statement=data["statement"],
                 written_by={"type": "ai", "model": model, "prompt_version": PROMPT_VERSION})


def submit_note(llm, store: Store, text: str, author: str, doc: str | None = None,
                location: str | None = None, created_at: str = "") -> SubmitResult:
    masked_text, masked = PIIGuard().mask(text, deep=False)
    name = doc or f"note_{hashlib.sha256(f'{author}{masked_text}'.encode('utf-8')).hexdigest()[:12]}"
    source, is_new = store.add_source(name, masked_text, author, location, created_at)
    result = SubmitResult(source, is_new, masked)
    if not is_new:
        return result
    model = getattr(llm, "model", "unknown")
    before = store.all_claims()
    for offset, chunk in split_note(masked_text):
        extracted = extract_claims(llm, chunk, shown_names(chunk, store.topics()),
                                   shown_names(chunk, store.condition_keys()))
        if extracted.error:
            result.errors.append(extracted.error)
        for item in extracted.stored:
            seen = tuple(sorted(claim.id for claim in before if claim.topic == item.data["topic"]))
            result.claims.append(store.add_claim(to_claim(item, offset, source, seen, model)))
    result.relations = [(new.id, old.id, kind) for new in result.claims for old in before
                        if (kind := relation(new, old)) != NONE]
    return result
