"""서버 LLM 연결 (D14). vLLM의 OpenAI 호환 주소로 JSON을 받는다.

- temperature 0, JSON 스키마 강제, 추론 모드는 기본 끔(HARNESS_V2_THINKING=1로 켬).
- 주소를 쉼표로 여러 개 주면 요청을 번갈아 보낸다(GPU마다 서버 하나).
- 모든 호출을 JSONL 파일 하나에 남긴다. 같은 입력은 이 기록을 다시 써서 서버 없이 재채점할 수 있다.
  파일 하나만 쓰는 이유: 학교 NAS는 작은 파일을 많이 만드는 작업에 약하다.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import threading
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


class LLMError(RuntimeError):
    """서버 호출 실패 또는 JSON으로 읽을 수 없는 응답."""


class ServerLLM:
    def __init__(self, base_url: str | None = None, model: str | None = None,
                 log_path: str | Path | None = None, max_tokens: int | None = None,
                 timeout: float = 600.0, thinking: bool | None = None):
        urls = base_url or os.environ.get("HARNESS_V2_BASE_URL", "http://127.0.0.1:8000/v1")
        self.base_urls = [url.strip().rstrip("/") for url in urls.split(",")]
        self._next_url = itertools.cycle(self.base_urls)
        self.model = model or os.environ.get("HARNESS_V2_MODEL", "Qwen/Qwen3-8B")
        self.log_path = Path(log_path or os.environ.get("HARNESS_V2_LOG", ROOT / ".cache" / "v2_calls.jsonl"))
        self.thinking = os.environ.get("HARNESS_V2_THINKING") == "1" if thinking is None else thinking
        self.max_tokens = max_tokens or (8192 if self.thinking else 2048)
        self.timeout = timeout
        self.stats = {"calls": 0, "cache_hits": 0, "with_reasoning": 0}
        self._lock = threading.Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, str] = {}
        if self.log_path.exists():
            with self.log_path.open(encoding="utf-8") as log:
                for line in log:
                    record = json.loads(line)
                    self._cache[record["key"]] = record["output"]

    def _key(self, prompt_version: str, system: str, user: str, schema: dict) -> str:
        blob = json.dumps([self.model, self.thinking, prompt_version, system, user, schema], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def complete_json(self, *, prompt_version: str, system: str, user: str, schema: dict) -> dict:
        key = self._key(prompt_version, system, user, schema)
        raw = self._cache.get(key)
        if raw is not None:
            self.stats["cache_hits"] += 1
        else:
            raw, reasoning_chars = self._post(system, user, schema)
            record = {"key": key, "model": self.model, "thinking": self.thinking, "prompt_version": prompt_version,
                      "reasoning_chars": reasoning_chars, "output": raw}
            with self._lock:
                self.stats["calls"] += 1
                self.stats["with_reasoning"] += reasoning_chars > 0
                self._cache[key] = raw
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps(record, ensure_ascii=False) + "\n")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"JSON 해석 실패: {raw[:200]}") from exc

    def _post(self, system: str, user: str, schema: dict) -> tuple[str, int]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}},
            "chat_template_kwargs": {"enable_thinking": self.thinking},
        }
        try:
            with self._lock:
                base_url = next(self._next_url)
            response = httpx.post(f"{base_url}/chat/completions", json=body, timeout=self.timeout)
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise LLMError(f"서버 호출 실패: {exc}") from exc
        if message.get("content") is None:
            raise LLMError("응답 본문 없음: 추론 중 길이 한도에 걸렸을 수 있음")
        return message["content"], len(message.get("reasoning_content") or "")
