"""Graphiti 연결 확인: Neo4j 접속 → 에피소드 1개 입력 → 검색. 본 실험 전에 한 번 돌려본다.

    python -m scripts.graphiti_smoke
"""
import asyncio
import os
from datetime import datetime, timezone

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType


async def main():
    assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY가 설정되지 않았습니다"
    g = Graphiti(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                 os.environ.get("NEO4J_USER", "neo4j"),
                 os.environ.get("NEO4J_PASSWORD", "password"))
    try:
        await g.build_indices_and_constraints()
        print("1/3 Neo4j 접속 OK")
        res = await g.add_episode(
            name="smoke", episode_body="정시찬: 피처 12개, 데이터 v1에서 XGBoost AUC 0.842로 가장 좋았다.",
            source=EpisodeType.text, source_description="smoke test", group_id="smoke_test",
            reference_time=datetime.now(timezone.utc))
        print(f"2/3 에피소드 입력 OK: 사실 {len(res.edges)}개 추출")
        for e in await g.search("XGBoost 성능", group_ids=["smoke_test"]):
            print(f"3/3 검색 OK: {e.fact}")
    finally:
        await g.close()


asyncio.run(main())
