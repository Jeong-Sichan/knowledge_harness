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
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

from pathlib import Path

from harness.context import answer_with_llm, raw_context
from harness.schema import ANSWERED, NO_EVIDENCE, Query, Record, Response
from harness.verifier import SourceStore

KST = timezone(timedelta(hours=9))


class GraphitiBaseline:
    name = "graphiti"

    def __init__(self, sources_dir: str | Path, answerer: str = "rule", k: int = 5,
                 graphiti=None, group_id: str | None = None):
        if graphiti is None:
            from graphiti_core import Graphiti

            graphiti = Graphiti(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                                os.environ.get("NEO4J_USER", "neo4j"),
                                os.environ.get("NEO4J_PASSWORD", "password"))
        self.g = graphiti
        self.k = k
        self.answerer = answerer
        self.sources = SourceStore(sources_dir)
        self.group_id = group_id or f"harness_eval_{datetime.now():%Y%m%d_%H%M%S}"
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
            for attempt in range(4):
                try:
                    result = self._run(self.g.add_episode(
                        name=r.id, episode_body=body, source=EpisodeType.text,
                        source_description="team record", group_id=self.group_id,
                        reference_time=datetime.fromisoformat(r.created_at).replace(tzinfo=KST)))
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
            print(f"  [graphiti] {i}/{len(ordered)} {r.id}: 사실 {len(result.edges)}개 "
                  f"(경과 {elapsed / 60:.1f}분, 남은 예상 {eta / 60:.1f}분)", flush=True)

    def ask(self, q: Query) -> Response:
        edges = self._run(self.g.search(q.question, group_ids=[self.group_id], num_results=self.k))
        # Graphiti가 무효 처리한 사실(invalid_at / expired_at)은 답에 쓰지 않는다
        valid = [e for e in edges if e.invalid_at is None and e.expired_at is None]
        if self.answerer == "llm":
            context = [f"[{','.join(self._record_ids([e])) or '출처 불명'}] {e.fact}" for e in valid]
            return answer_with_llm(q.question, context)
        if not valid:
            return Response(NO_EVIDENCE, [], [], 0, answer="관련 사실 없음")
        ids = self._record_ids(valid)
        facts = [e.fact for e in valid]
        # Graphiti에는 승인 상태 개념이 없으므로 유효한 사실은 모두 팀 사실로 제시된다.
        # 독립 근거 수는 Graphiti가 돌려준 사실 개수로 센다(재인용을 구분하지 않음).
        return Response(ANSWERED, ids, ids, len(valid), answer=" / ".join(facts), exposed=facts)

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
