"""PII 차단 모듈(PII Guard): 민감 정보가 팀 공유 기록으로 퍼지기 전에 가린다.

문제의식과 같은 축이다. 근거의 범위(조건·승인)뿐 아니라 공개 범위도 공유되는 동안 넓어지면 안 된다.

1단계는 정규식으로 형식이 정해진 정보(전화번호, 이메일, 주민번호, API 키)를 잡는다.
이름처럼 형식이 없는 정보는 작은 모델 판정 자리(`llm_detector`)로 넘긴다(선택).
인용 검증은 원문 기준이므로 검증이 끝난 뒤에 가린다(store.py 참고).
"""
from __future__ import annotations

import re
from typing import Callable

PATTERNS: dict[str, re.Pattern] = {
    "rrn": re.compile(r"\b\d{6}-[1-4]\d{6}\b"),                      # 주민등록번호
    "phone": re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"),           # 휴대전화
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "api_key": re.compile(r"\b(?:sk|pk|api|key)[-_](?:live[-_]|test[-_])?[A-Za-z0-9]{16,}\b"),
}


class PIIGuard:
    def __init__(self, llm_detector: Callable[[str], list[str]] | None = None):
        self.llm_detector = llm_detector  # 텍스트 → 가려야 할 문자열 목록. 작은 모델 자리.
        self.stats = {"checked": 0, "masked_records": 0, "masked_spans": 0}

    def mask(self, text: str, deep: bool = True) -> tuple[str, list[str]]:
        """가린 텍스트와 발견한 종류 목록을 돌려준다.

        정규식으로 먼저 가린 뒤에 남은 텍스트만 모델 판정(llm_detector)에 넘긴다.
        그래서 전화번호·이메일·키는 판정 모델에도 가지 않는다(실명은 간다 → 운영에서는 로컬 NER 모델 권장).
        deep=False면 정규식만 쓴다(짧은 값·인용처럼 이미 본문에서 검사한 조각).
        """
        self.stats["checked"] += 1
        kinds = []
        for kind, pat in PATTERNS.items():
            for span in set(m.group() for m in pat.finditer(text)):
                text = text.replace(span, f"[{kind.upper()} 가림]")
                kinds.append(kind)
        if deep and self.llm_detector is not None:
            for span in self.llm_detector(text):
                if span and span in text:
                    text = text.replace(span, "[NAME 가림]")
                    kinds.append("name")
        self.stats["masked_spans"] += len(kinds)
        return text, kinds
