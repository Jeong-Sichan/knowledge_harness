"""스트롱 베이스라인: Graphiti (https://github.com/getzep/graphiti)

Graphiti는 출처 추적(에피소드)과 시간 기반 무효화(충돌 시 옛 사실을 invalid 처리)가 있는 지식 그래프다.
우리가 짚는 페인 포인트:
  1. 조건이 다른 관찰을 '충돌'로 보고 하나를 무효 처리할 수 있다
  2. 작성 주체(사람/AI)와 팀 승인 상태 구분이 없다
  3. 같은 근거를 다시 인용한 것을 독립 근거로 셀 수 있다
  4. 원문과 인용을 검증하는 계층이 없다
  5. 민감 정보(PII)가 공유 기록으로 퍼지는 걸 막는 계층이 없다

필요한 것: `pip install graphiti-core`(0.31.2에서 API 확인), Neo4j, OPENAI_API_KEY(Graphiti 기본 LLM·임베더).
환경변수 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 로 접속 정보를 바꾼다.
실행할 때마다 새 group_id를 써서 이전 실행의 그래프가 결과에 섞이지 않게 한다.

튜닝된 Graphiti(tuned=True, 시스템 이름 graphiti_tuned):
기본 설정의 Graphiti는 사실을 요약하면서 조건·승인 상태·작성자 유형을 잃었다(2차 실험).
"설정을 안 해서 약해진 베이스라인"이라는 반론을 막으려고, Graphiti가 공식 지원하는 두 장치로 이 정보를 지키게 한다.
  1. edge_types: 사실(edge)마다 기록 id·피처 수·데이터 버전·승인 상태·작성자 유형을 속성으로 뽑는 맞춤 스키마
  2. custom_extraction_instructions: 사실 문장에 조건·승인 상태·작성자를 빠짐없이 남기라는 추출 지시
     (Graphiti는 맞춤 속성을 원본 기록이 아니라 자기가 쓴 사실 문장에서 뽑으므로 2가 없으면 1이 비게 된다)
답변기에는 사실 문장과 함께 뽑힌 속성도 넘긴다.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

from pathlib import Path

from pydantic import BaseModel, Field

from harness.context import answer_with_llm, raw_context
from harness.schema import ANSWERED, NO_EVIDENCE, Query, Record, Response
from harness.verifier import SourceStore

KST = timezone(timedelta(hours=9))


class TeamFinding(BaseModel):
    """팀 기록이 주장하는 실험 결과나 결정. 어떤 조건에서, 누가 올렸고, 팀이 승인했는지를 함께 담는다."""
    record_id: str | None = Field(None, description="근거가 된 팀 기록 번호 (예: R01)")
    n_features: int | None = Field(None, description="결과가 나온 실험의 피처 수. 기록이나 원문에 없으면 비운다")
    dataset: str | None = Field(None, description="결과가 나온 데이터 버전 (예: v1, v2). 없으면 비운다")
    approval_status: str | None = Field(None, description="팀 승인 상태: approved 또는 candidate")
    author_type: str | None = Field(None, description="기록 작성자 유형: human 또는 ai")


TUNED_EDGE_TYPES = {"TeamFinding": TeamFinding}

TUNED_INSTRUCTIONS = (
    "이 에피소드는 팀 공유 기록 하나와 그 기록이 인용한 실험 원문이다. 사실을 뽑을 때 다음을 지켜라.\n"
    "- 각 사실 문장에 기록 번호, 실험 조건(피처 수, 데이터 버전), 작성자와 작성자 유형(human/ai), "
    "승인 상태(approved/candidate)를 빠짐없이 적는다. 조건은 원문의 '조건:' 줄에서 찾는다.\n"
    "- 조건(피처 수, 데이터 버전)이 다른 결과는 서로 모순이 아니다. 조건이 같고 결론이 다를 때만 모순이다.\n"
    "- 기록이 원문을 인용했다고 해도, 원문에 그 문장이 실제로 없으면 사실로 만들지 않는다."
)


class GraphitiBaseline:
    name = "graphiti"

    def __init__(self, sources_dir: str | Path, answerer: str = "rule", k: int = 5,
                 graphiti=None, group_id: str | None = None, tuned: bool = False):
        if graphiti is None:
            from graphiti_core import Graphiti

            graphiti = Graphiti(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                                os.environ.get("NEO4J_USER", "neo4j"),
                                os.environ.get("NEO4J_PASSWORD", "password"))
        self.g = graphiti
        self.tuned = tuned
        if tuned:
            self.name = "graphiti_tuned"
        self.k = k
        self.answerer = answerer
        self.sources = SourceStore(sources_dir)
        self.group_id = group_id or f"harness_eval_{'tuned_' if tuned else ''}{datetime.now():%Y%m%d_%H%M%S}"
        self.episode_to_record: dict[str, str] = {}
        self.loop = asyncio.new_event_loop()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def ingest(self, records: list[Record]) -> None:
        from graphiti_core.nodes import EpisodeType

        self._run(self.g.build_indices_and_constraints())
        ordered = sorted(records, key=lambda r: r.created_at)
        start = time.time()
        for i, r in enumerate(ordered, 1):
            # 다른 시스템과 같은 원재료: 기록 원본 + 인용한 원문 문서
            body = "\n".join(raw_context([r], self.sources))
            extra = ({"edge_types": TUNED_EDGE_TYPES, "custom_extraction_instructions": TUNED_INSTRUCTIONS}
                     if self.tuned else {})
            for attempt in range(4):
                try:
                    result = self._run(self.g.add_episode(
                        name=r.id, episode_body=body, source=EpisodeType.text,
                        source_description="team record", group_id=self.group_id,
                        reference_time=datetime.fromisoformat(r.created_at).replace(tzinfo=KST), **extra))
                    break
                except Exception as e:  # 속도 제한 등 일시 오류는 기다렸다가 다시 시도
                    if attempt == 3:
                        raise
                    wait = 10 * 2 ** attempt
                    print(f"  [graphiti] {r.id} 실패({type(e).__name__}), {wait}초 후 재시도", flush=True)
                    time.sleep(wait)
            self.episode_to_record[result.episode.uuid] = r.id
            elapsed = time.time() - start
            eta = elapsed / i * (len(ordered) - i)
            print(f"  [{self.name}] {i}/{len(ordered)} {r.id}: 사실 {len(result.edges)}개 "
                  f"(경과 {elapsed / 60:.1f}분, 남은 예상 {eta / 60:.1f}분)", flush=True)

    def ask(self, q: Query) -> Response:
        edges = self._run(self.g.search(q.question, group_ids=[self.group_id], num_results=self.k))
        # Graphiti가 무효 처리한 사실(invalid_at / expired_at)은 답에 쓰지 않는다
        valid = [e for e in edges if e.invalid_at is None and e.expired_at is None]
        if self.answerer == "llm":
            context = [self._fact_line(e) for e in valid]
            return answer_with_llm(q.question, context)
        if not valid:
            return Response(NO_EVIDENCE, [], [], 0, answer="관련 사실 없음")
        ids = self._record_ids(valid)
        facts = [e.fact for e in valid]
        # Graphiti에는 승인 상태 개념이 없으므로 유효한 사실은 모두 팀 사실로 제시된다.
        # 독립 근거 수는 Graphiti가 돌려준 사실 개수로 센다(재인용을 구분하지 않음).
        return Response(ANSWERED, ids, ids, len(valid), answer=" / ".join(facts), exposed=facts)

    def _fact_line(self, e) -> str:
        line = f"[{','.join(self._record_ids([e])) or '출처 불명'}] {e.fact}"
        attrs = {k: v for k, v in (getattr(e, "attributes", None) or {}).items() if v not in (None, "")}
        if self.tuned and attrs:
            line += " (속성: " + ", ".join(f"{k}={v}" for k, v in sorted(attrs.items())) + ")"
        return line

    def _record_ids(self, edges) -> list[str]:
        ids: list[str] = []
        for e in edges:
            for ep in e.episodes:
                rid = self.episode_to_record.get(ep)
                if rid and rid not in ids:
                    ids.append(rid)
        return ids

    def invalidated_facts(self) -> list[tuple[str, str]]:
        """Graphiti가 충돌로 보고 무효 처리한 사실. 페인 포인트 1(조건이 다른데 무효화)을 확인하는 데 쓴다."""
        edges = self._run(self.g.search("모델 피처 데이터 결측치 불균형", group_ids=[self.group_id],
                                        num_results=50))
        return [(e.fact, str(e.invalid_at or e.expired_at)) for e in edges
                if e.invalid_at is not None or e.expired_at is not None]

    def close(self):
        self._run(self.g.close())
        self.loop.close()
