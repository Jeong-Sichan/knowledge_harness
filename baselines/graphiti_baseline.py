"""스트롱 베이스라인: Graphiti (https://github.com/getzep/graphiti)

Graphiti는 출처 추적(에피소드)과 시간 기반 무효화(충돌 시 옛 사실을 invalid 처리)가 있는 지식 그래프다.
우리가 짚는 페인 포인트:
  1. 조건이 다른 관찰을 '충돌'로 보고 하나를 무효 처리할 수 있다
  2. 작성 주체(사람/AI)와 팀 승인 상태 구분이 없다
  3. 같은 근거를 다시 인용한 것을 독립 근거로 셀 수 있다
  4. 원문과 인용을 검증하는 계층이 없다
  5. 민감 정보(PII)가 공유 기록으로 퍼지는 걸 막는 계층이 없다

필요한 것: `pip install graphiti-core`, Neo4j(예: docker run -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5),
기본 설정 기준 OPENAI_API_KEY(Graphiti 기본 LLM·임베더). 다른 LLM 클라이언트는 Graphiti 문서를 참고.

TODO(팀): graphiti-core 버전에 따라 add_episode 반환값과 EntityEdge 필드명이 다를 수 있으니
          설치 후 한 번 돌려보고 맞춰야 한다. 아래 코드는 아직 실제 Graphiti로 검증하지 않았다.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime

from harness.schema import ANSWERED, NO_EVIDENCE, Query, Record, Response


class GraphitiBaseline:
    name = "graphiti"

    def __init__(self, k: int = 5):
        from graphiti_core import Graphiti

        self.k = k
        self.g = Graphiti(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                          os.environ.get("NEO4J_USER", "neo4j"),
                          os.environ.get("NEO4J_PASSWORD", "password"))
        self.episode_to_record: dict[str, str] = {}
        self.loop = asyncio.new_event_loop()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def ingest(self, records: list[Record]) -> None:
        from graphiti_core.nodes import EpisodeType

        self._run(self.g.build_indices_and_constraints())
        for r in sorted(records, key=lambda r: r.created_at):
            # 기록 텍스트에 조건과 근거를 그대로 넣는다(Graphiti가 쓸 수 있는 정보는 동일하게 제공)
            body = (f"{r.author}: {r.text} (조건: {r.conditions}) "
                    f"근거: " + "; ".join(f"{e.source} \"{e.quote}\"" for e in r.evidence))
            result = self._run(self.g.add_episode(
                name=r.id, episode_body=body, source=EpisodeType.text,
                source_description="team record",
                reference_time=datetime.fromisoformat(r.created_at)))
            episode = getattr(result, "episode", None)
            if episode is not None:
                self.episode_to_record[episode.uuid] = r.id

    def ask(self, q: Query) -> Response:
        edges = self._run(self.g.search(q.question))[: self.k]
        valid = [e for e in edges if getattr(e, "invalid_at", None) is None]
        ids: list[str] = []
        for e in valid:
            for ep in getattr(e, "episodes", []) or []:
                rid = self.episode_to_record.get(ep)
                if rid and rid not in ids:
                    ids.append(rid)
        if not valid:
            return Response(NO_EVIDENCE, [], [], 0, answer="관련 사실 없음")
        # Graphiti에는 승인 상태 개념이 없으므로 유효한 사실은 모두 팀 사실로 제시된다
        return Response(ANSWERED, ids, ids, len(valid),
                        answer=" / ".join(e.fact for e in valid),
                        exposed=[e.fact for e in valid])

    def close(self):
        self._run(self.g.close())
