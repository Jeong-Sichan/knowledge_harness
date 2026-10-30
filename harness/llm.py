"""LLM 연동. 기본은 OpenAI(Graphiti와 같은 모델), HARNESS_LLM_PROVIDER=anthropic 으로 Claude도 쓸 수 있다.

공정 비교 프로토콜: 모든 시스템(하네스, 베이스라인)이 같은 답변기(`answer`)를 쓴다.
차이는 답변기에 넘기는 맥락(기억 계층)에서만 난다.

효율성 설계:
- 기록 구조화·질문 파싱은 작은 모델(HARNESS_SMALL_MODEL), 답변은 HARNESS_ANSWER_MODEL
- 같은 프롬프트는 디스크 캐시(.cache/llm_cache.json)에서 재사용 → 재실행·ablation 비용 0
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

PROVIDER = os.environ.get("HARNESS_LLM_PROVIDER", "openai")
_DEFAULTS = {
    "openai": ("gpt-6-luna", "gpt-6-luna"),            # graphiti-core 0.31 기본 모델과 같게
    "anthropic": ("claude-haiku-5-5", "claude-opus-5-5"),
}
SMALL_MODEL = os.environ.get("HARNESS_SMALL_MODEL", _DEFAULTS[PROVIDER][0])
ANSWER_MODEL = os.environ.get("HARNESS_ANSWER_MODEL", _DEFAULTS[PROVIDER][1])

_CACHE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "llm_cache.json"
_cache: dict[str, dict] | None = None
_client = None
stats = {"calls": 0, "cache_hits": 0}


def _load_cache() -> dict[str, dict]:
    global _cache
    if _cache is None:
        _cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8")) if _CACHE_PATH.exists() else {}
    return _cache


def _save_cache() -> None:
    """다른 실행이 동시에 쓴 항목을 합친 뒤 임시 파일 → 교체로 저장한다(터미널 두 개로 동시에 돌려도 안전)."""
    _CACHE_PATH.parent.mkdir(exist_ok=True)
    if _CACHE_PATH.exists():
        try:
            on_disk = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            _cache.update({k: v for k, v in on_disk.items() if k not in _cache})
        except (json.JSONDecodeError, OSError):
            pass
    tmp = _CACHE_PATH.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(_cache, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _CACHE_PATH)


def _parse(model: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
    key = hashlib.sha256(f"{PROVIDER}|{model}|{schema.__name__}|{prompt}".encode()).hexdigest()
    cache = _load_cache()
    if key in cache:
        stats["cache_hits"] += 1
        return schema.model_validate(cache[key])
    stats["calls"] += 1
    out = _parse_openai(model, prompt, schema) if PROVIDER == "openai" else _parse_anthropic(model, prompt, schema)
    cache[key] = out.model_dump()
    _save_cache()
    return out


def _parse_openai(model: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI()
    resp = _client.chat.completions.parse(
        model=model, response_format=schema, messages=[{"role": "user", "content": prompt}])
    msg = resp.choices[0].message
    if msg.parsed is None:
        raise RuntimeError(f"모델이 구조화 응답을 주지 않았습니다: {msg.refusal}")
    return msg.parsed


def _parse_anthropic(model: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    kwargs = dict(model=model, max_tokens=4000, output_format=schema,
                  messages=[{"role": "user", "content": prompt}])
    if model.startswith("claude-opus"):
        # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도
        resp = _client.beta.messages.parse(**kwargs, betas=["server-side-fallback-2026-07-01"],
                                           fallbacks="default")
    else:
        resp = _client.messages.parse(**kwargs)
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"모델이 응답을 거절했습니다: {resp.stop_details}")
    return resp.parsed_output


# ---------- 조건 스키마 (팀 결정 전 초안: 키 고정) ----------

def _conditions(n_features: int | None, dataset: str | None) -> dict:
    cond = {}
    if n_features is not None:
        cond["n_features"] = n_features
    if dataset:
        cond["dataset"] = dataset.strip().lower()
    return cond


_COND_RULES = ("- n_features: 사용한 피처 수(정수). 원문에 없으면 null\n"
               "- dataset: 데이터 버전(예: v1, v2). 원문에 없으면 null\n")


# ---------- 앞단: 기록 구조화 (작은 모델) ----------

class StructuredRecord(BaseModel):
    topic: str
    value: str
    n_features: int | None
    dataset: str | None


def structure_record(text: str, source_text: str, known: dict[str, list[str]]) -> tuple[str, str, dict]:
    """자유 텍스트 기록 → (topic, value, conditions). known은 {기존 topic: [기존 value, ...]}."""
    prompt = (
        "팀 실험 기록을 구조화하라.\n"
        "- topic: 주장이 답하는 질문의 종류를 snake_case 영어로. 기존 topic과 같은 종류면 반드시 그 이름을 그대로 쓴다.\n"
        "- value: 주장의 핵심 답(모델명, 수치, 방법명). 기존 value와 같은 뜻이면 그 표기를 그대로 쓴다.\n"
        + _COND_RULES +
        "- 조건은 기록 문장과 원문 문서 머리말의 '조건' 줄에서 찾는다.\n\n"
        f"<existing_topics>{json.dumps(known, ensure_ascii=False)}</existing_topics>\n"
        f"<record>{text}</record>\n<source>{source_text}</source>")
    out = _parse(SMALL_MODEL, prompt, StructuredRecord)
    return out.topic.strip(), out.value.strip(), _conditions(out.n_features, out.dataset)


# ---------- 앞단: 질문 파싱 (작은 모델) ----------

class ParsedQuery(BaseModel):
    topic: str
    n_features: int | None
    dataset: str | None


def parse_query(question: str, known_topics: list[str]) -> tuple[str | None, dict]:
    prompt = (
        "팀원의 질문을 파싱하라.\n"
        "- topic: 아래 목록 중 질문이 묻는 것. 해당하는 게 없으면 unknown\n"
        + _COND_RULES +
        f"\n<topics>{json.dumps(known_topics, ensure_ascii=False)}</topics>\n<question>{question}</question>")
    out = _parse(SMALL_MODEL, prompt, ParsedQuery)
    topic = out.topic.strip()
    return (topic if topic in known_topics else None), _conditions(out.n_features, out.dataset)


# ---------- 공통 답변기: 모든 시스템이 같은 프롬프트·모델로 답한다 ----------

class LLMAnswer(BaseModel):
    status: Literal["answered", "conflict", "only_unapproved", "no_evidence"]
    supporting_ids: list[str]
    team_fact_ids: list[str]
    independent_evidence: int
    answer: str


ANSWER_INSTRUCTIONS = """너는 팀 공유 기록을 근거로 팀원의 질문에 답하는 AI다. 아래 맥락만 근거로 쓴다.

판단 규칙:
- 질문의 조건(피처 수, 데이터 버전 등)과 맞는 기록만 근거로 쓴다. 조건이 다른 기록으로 답을 일반화하지 않는다.
- 원문과 맞지 않는 인용을 가진 기록은 근거로 쓰지 않는다.
- status는 다음 중 하나다.
  answered: 조건에 맞고 팀이 승인(approved)한 근거로 답할 수 있다
  conflict: 같은 조건에서 서로 다른 주장이 있다
  only_unapproved: 조건에 맞는 근거가 승인 전 후보(candidate)뿐이다
  no_evidence: 조건에 맞는 근거가 없다
- supporting_ids: 답의 근거로 쓴 기록 id(R로 시작). 없으면 빈 목록
- team_fact_ids: 그중 팀이 승인한 사실로 제시한 기록 id
- independent_evidence: 서로 독립인 근거 수. 같은 원문·버전·구간을 다시 인용한 기록은 1개로 센다
- answer: 팀원에게 할 한국어 답변. 확실한 부분과 아닌 부분을 구분한다.
"""


def answer(question: str, context: list[str]) -> LLMAnswer:
    prompt = (ANSWER_INSTRUCTIONS + "\n<context>\n" + "\n".join(context) + "\n</context>\n"
              f"<question>{question}</question>")
    return _parse(ANSWER_MODEL, prompt, LLMAnswer)


# ---------- PII 차단: 형식 없는 민감 정보(이름 등) 찾기 (작은 모델) ----------

class PIISpans(BaseModel):
    spans: list[str]


def detect_pii_spans(text: str) -> list[str]:
    """`PIIGuard(llm_detector=detect_pii_spans)`로 연결한다. 정규식이 못 잡는 실명·주소 등을 찾는다."""
    prompt = (
        "아래 팀 기록에서 개인을 식별할 수 있는 정보(실명, 주소, 계정명 등)를 원문 그대로 뽑아라. "
        "모델명·수치·실험 조건·팀원 이름(작성자)은 제외한다. 없으면 빈 목록.\n\n"
        f"<record>{text}</record>")
    return _parse(SMALL_MODEL, prompt, PIISpans).spans
