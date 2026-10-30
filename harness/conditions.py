"""조건 비교 규칙.

- 기록에 없는 조건 키는 '제한 없음'으로 본다(와일드카드).
- 질문과 기록 모두에 있는 키의 값이 다르면 조건이 맞지 않는다.
"""
from __future__ import annotations

from typing import Any


def mismatched_keys(query_cond: dict[str, Any], record_cond: dict[str, Any]) -> list[str]:
    return [k for k, v in query_cond.items() if k in record_cond and record_cond[k] != v]


def is_compatible(query_cond: dict[str, Any], record_cond: dict[str, Any]) -> bool:
    return not mismatched_keys(query_cond, record_cond)


def same_conditions(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a == b


def describe(cond: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(cond.items())) or "조건 없음"
