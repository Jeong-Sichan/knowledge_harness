"""LLM 연동(선택). `pip install anthropic pydantic` 후 ANTHROPIC_API_KEY가 있으면 쓴다.

효율성 설계: 모듈마다 모델 크기를 다르게 쓴다.
- 앞단(기록 구조화, 질문 파싱): 작은 모델 → 호출이 많고 형식 변환 위주
- 인용 검증 애매 구간, 전체 맥락 베이스라인: 큰 모델 → 호출은 적고 정확도가 중요
모델은 환경변수 HARNESS_SMALL_MODEL / HARNESS_LARGE_MODEL로 바꿀 수 있다.
"""
from __future__ import annotations

import json
import os

from pydantic import BaseModel

SMALL_MODEL = os.environ.get("HARNESS_SMALL_MODEL", "claude-haiku-5-5")
LARGE_MODEL = os.environ.get("HARNESS_LARGE_MODEL", "claude-opus-5-5")
# 큰 모델이 안전 분류기로 응답을 거절하면 서버가 다른 모델로 자동 재시도한다
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def _parse(model: str, prompt: str, schema: type[BaseModel], max_tokens: int = 4000):
    if model == LARGE_MODEL and model.startswith("claude-opus"):
        resp = client().beta.messages.parse(
            model=model, max_tokens=max_tokens, output_format=schema,
            messages=[{"role": "user", "content": prompt}],
            betas=[_FALLBACK_BETA], fallbacks="default")
    else:
        resp = client().messages.parse(
            model=model, max_tokens=max_tokens, output_format=schema,
            messages=[{"role": "user", "content": prompt}])
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"모델이 응답을 거절했습니다: {resp.stop_details}")
    return resp.parsed_output


# ---------- 앞단: 기록 구조화 (작은 모델) ----------

class Condition(BaseModel):
    key: str
    value: str


class StructuredRecord(BaseModel):
    topic: str
    value: str
    conditions: list[Condition]
    quote: str


def structure_record(text: str, source_text: str, known_topics: list[str]) -> StructuredRecord:
    prompt = (
        "팀 실험 기록을 구조화하라.\n"
        f"- topic은 가능하면 기존 목록에서 고른다: {known_topics}\n"
        "- value는 주장의 핵심 값(모델명, 수치 등)\n"
        "- conditions는 주장이 성립하는 실험 조건(n_features, dataset 등). 원문에 있는 것만 적는다.\n"
        "- quote는 주장을 뒷받침하는 원문 구간을 그대로 복사한다.\n\n"
        f"<record>{text}</record>\n<source>{source_text}</source>")
    return _parse(SMALL_MODEL, prompt, StructuredRecord)


# ---------- 인용 검증 애매 구간 (큰 모델) ----------

class QuoteVerdict(BaseModel):
    faithful: bool
    reason: str


def judge_quote(source_text: str, quote: str) -> bool:
    prompt = (
        "아래 인용이 원문 내용을 왜곡 없이 옮긴 것인지 판단하라. 숫자·방향·조건이 하나라도 다르면 false.\n\n"
        f"<source>{source_text}</source>\n<quote>{quote}</quote>")
    return _parse(LARGE_MODEL, prompt, QuoteVerdict).faithful


# ---------- 베이스라인: 전체 기록을 표로 넣고 LLM이 답하게 함 (큰 모델) ----------

class LLMAnswer(BaseModel):
    status: str  # answered | conflict | only_unapproved | no_evidence
    supporting_ids: list[str]
    team_fact_ids: list[str]
    independent_evidence: int
    answer: str


def full_context_answer(question: str, records_table: list[dict]) -> LLMAnswer:
    prompt = (
        "다음은 팀의 공유 기록 표다. 질문에 답하라.\n"
        "status는 answered(답할 수 있음), conflict(같은 조건에서 주장 충돌), "
        "only_unapproved(근거가 승인 전 후보뿐), no_evidence(질문 조건에 맞는 근거 없음) 중 하나.\n"
        "supporting_ids는 답의 근거로 쓴 기록 id, team_fact_ids는 그중 팀 합의 사실로 제시한 기록 id, "
        "independent_evidence는 서로 독립인 근거 수다.\n\n"
        f"<records>{json.dumps(records_table, ensure_ascii=False)}</records>\n<question>{question}</question>")
    return _parse(LARGE_MODEL, prompt, LLMAnswer)
