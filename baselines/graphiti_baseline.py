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
from datetime import datetime, timedelta, timezone

from harness.schema import ANSWERED, NO_EVIDENCE, Query, Record, Response

KST = timezone(timedelta(hours=9))


def record_to_episode(r: Record) -> str:
    """Graphiti에도 우리 하네스와 같은 정보(작성자, 조건, 승인 상태, 근거)를 텍스트로 준다."""
    evidence = "; ".join(f"{e.source} rev{e.rev} \"{e.quote}\"" for e in r.evidence)
    return (f"[{r.id}] 작성자 {r.author}({r.author_type}), 상태 {r.status}. "
            f"주장: {r.text} 조건: {r.conditions}. 근거: {evidence}")


class GraphitiBaseline:
    name = "graphiti"

    def __init__(self, k: int = 5, graphiti=None, group_id: str | None = None):
        if graphiti is None:
            from graphiti_core import Graphiti

            graphiti = Graphiti(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                                os.environ.get("NEO4J_USER", "neo4j"),
                                os.environ.get("NEO4J_PASSWORD", "password"))
        self.g = graphiti
        self.k = k
        self.group_id = group_id or f"harness_eval_{datetime.now():%Y%m%d_%H%M%S}"
        self.episode_to_record: dict[str, str] = {}
        self.loop = asyncio.new_event_loop()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def ingest(self, records: list[Record]) -> None:
        from graphiti_core.nodes import EpisodeType

        self._run(self.g.build_indices_and_constraints())
        for r in sorted(records, key=lambda r: r.created_at):
            result = self._run(self.g.add_episode(
                name=r.id, episode_body=record_to_episode(r), source=EpisodeType.text,
                source_description="team record", group_id=self.group_id,
                reference_time=datetime.fromisoformat(r.created_at).replace(tzinfo=KST)))
            self.episode_to_record[result.episode.uuid] = r.id
            print(f"  [graphiti] {r.id} 입력: 사실 {len(result.edges)}개 추출")

    def ask(self, q: Query) -> Response:
        edges = self._run(self.g.search(q.question, group_ids=[self.group_id], num_results=self.k))
        # Graphiti가 무효 처리한 사실(invalid_at / expired_at)은 답에 쓰지 않는다
        valid = [e for e in edges if e.invalid_at is None and e.expired_at is None]
        if not valid:
            return Response(NO_EVIDENCE, [], [], 0, answer="관련 사실 없음")
        ids: list[str] = []
        for e in valid:
            for ep in e.episodes:
                rid = self.episode_to_record.get(ep)
                if rid and rid not in ids:
                    ids.append(rid)
        facts = [e.fact for e in valid]
        # Graphiti에는 승인 상태 개념이 없으므로 유효한 사실은 모두 팀 사실로 제시된다.
        # 독립 근거 수는 Graphiti가 돌려준 사실 개수로 센다(재인용을 구분하지 않음).
        return Response(ANSWERED, ids, ids, len(valid), answer=" / ".join(facts), exposed=facts)

    def invalidated_facts(self) -> list[tuple[str, str]]:
        """Graphiti가 충돌로 보고 무효 처리한 사실. 페인 포인트 1(조건이 다른데 무효화)을 확인하는 데 쓴다."""
        edges = self._run(self.g.search("모델 피처 데이터 결측치 불균형", group_ids=[self.group_id],
                                        num_results=50))
        return [(e.fact, str(e.invalid_at or e.expired_at)) for e in edges
                if e.invalid_at is not None or e.expired_at is not None]

    def close(self):
        self._run(self.g.close())
        self.loop.close()
