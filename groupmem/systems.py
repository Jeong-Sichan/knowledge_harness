"""GroupMemBench 작은 세트에서 비교하는 시스템들. 모두 retrieve(question, asker) -> (passages, msg_ids)를 돌려준다.

- bm25: GroupMemBench의 BM25 베이스라인과 같은 방식(내용만 색인, 상위 k개)
- harness: 우리 하네스의 대화용 어댑터. 기록 입력 때 LLM을 쓰지 않고 공개 메타데이터만 쓴다.
    1. 범위 지정(조건 필터): 질문이 단계·주제·채널 이름을 말하면 그 범위의 메시지만 근거로 쓴다
    2. 최신성 표시(관계 판정): 같은 단계·주제 안에서 더 나중 메시지가 있으면 이전 메시지에 표시한다
    3. 범위 안에 근거가 없으면 그 사실을 답변기에 알린다(근거 없음 판정)
  인용 검증·재인용 묶기는 이 데이터에 원문 문서와 인용이 없어 쓰지 않는다.
- graphiti / graphiti_tuned: 메시지를 에피소드로 넣고 사실(edge)을 검색한다. 무효 처리된 사실은 뺀다.
  튜닝 버전은 사실마다 단계·주제·역할·메시지 번호·시각을 속성으로 뽑는 맞춤 스키마와 추출 지시를 준다.
"""
from __future__ import annotations

import asyncio
import html
import os
import time
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from harness.retriever import BM25

from .subset import words


def format_passage(m: dict) -> str:
    """GroupMemBench eval_lib.format_retrieved_message와 같은 머리말 형식."""
    tags = [f"user={m.get('author') or '?'}"]
    for key, label in (("role", "speaker_role"), ("_channel", "channel"), ("phase_name", "phase_name"),
                       ("topic", "topic"), ("timestamp", "timestamp"), ("reply_to", "reply_to"),
                       ("msg_node", "msg_node")):
        if m.get(key) not in (None, ""):
            tags.append(f"{label}={m[key]}")
    return f"[{' / '.join(tags)}]\n{html.unescape(m.get('content') or '').strip()}".strip()


def query_text(question: str, asker: str) -> str:
    return f"{asker} {question}" if asker else question  # GroupMemBench 검색 질의와 같다


class BM25System:
    name = "bm25"

    def __init__(self, k: int = 10):
        self.k = k

    def ingest(self, msgs: list[dict]) -> None:
        self.msgs = msgs
        self.bm25 = BM25([html.unescape(m["content"]) for m in msgs], tokenizer=words)

    def ranked(self, query: str) -> list[int]:
        scores = self.bm25.scores(query)
        return [i for i in sorted(range(len(self.msgs)), key=lambda i: -scores[i]) if scores[i] > 0]

    def retrieve(self, question: str, asker: str) -> tuple[list[str], list[str]]:
        top = [self.msgs[i] for i in self.ranked(query_text(question, asker))[: self.k]]
        return [format_passage(m) for m in top], [m["msg_node"] for m in top]


class HarnessGMB(BM25System):
    name = "harness"

    def __init__(self, k: int = 10, pool: int = 30):
        super().__init__(k)
        self.pool = pool

    def ingest(self, msgs: list[dict]) -> None:
        super().ingest(msgs)
        self.scopes = {s for m in msgs for s in (m["phase_name"], m["topic"], m["_channel"]) if s}

    def retrieve(self, question: str, asker: str) -> tuple[list[str], list[str]]:
        pool = [self.msgs[i] for i in self.ranked(query_text(question, asker))[: self.pool]]
        q = question.lower()
        named = sorted(s for s in self.scopes if s.lower() in q)
        notes = []
        if named:
            scoped = [m for m in pool if {m["phase_name"], m["topic"], m["_channel"]} & set(named)]
            notes.append("질문이 가리키는 범위: " + ", ".join(named))
            if not scoped:
                notes.append("그 범위의 메시지가 검색되지 않았다. 다른 범위의 메시지로 답을 일반화하지 말고, "
                             "근거가 없으면 없다고 답한다.")
            pool = scoped or pool
        top = pool[: self.k]
        # 같은 단계·주제 안에서는 최신 메시지를 먼저, 이전 메시지에는 표시를 붙인다
        latest: dict[tuple, str] = {}
        for m in top:
            g = (m["phase_name"], m["topic"])
            latest[g] = max(latest.get(g, ""), m["timestamp"])
        top.sort(key=lambda m: (m["phase_name"], m["topic"], m["timestamp"]), reverse=True)
        passages = []
        for m in top:
            mark = ("[최신: 같은 단계·주제에서 가장 나중 메시지]" if m["timestamp"] == latest[(m["phase_name"], m["topic"])]
                    else "[이전: 같은 단계·주제에 더 나중 메시지가 있어 대체되었을 수 있음]")
            passages.append(f"{mark} {format_passage(m)}")
        notes.append("같은 단계·주제에서는 더 나중 메시지가 이전 결정을 바꿀 수 있다. '현재' 상태를 물으면 최신 메시지를 따른다.")
        return ["[하네스 안내] " + " ".join(notes)] + passages, [m["msg_node"] for m in top]


class ChannelFact(BaseModel):
    """팀 채널 대화에서 나온 사실이나 결정. 어느 단계·주제에서, 누가(역할), 언제 말했는지 함께 담는다."""
    phase_name: str | None = Field(None, description="메시지가 속한 업무 단계 이름")
    topic: str | None = Field(None, description="메시지의 스레드 주제")
    speaker_role: str | None = Field(None, description="말한 사람의 역할 (예: Compliance Officer)")
    source_msg: str | None = Field(None, description="근거 메시지 번호 (예: Msg_835)")
    stated_at: str | None = Field(None, description="메시지 시각 (ISO 8601)")


TUNED_INSTRUCTIONS = (
    "이 에피소드는 팀 채널 메시지 하나다. 머리말 [...]에 작성자, 역할, 채널, 단계(phase_name), 주제(topic), 시각, "
    "메시지 번호가 있다. 사실을 뽑을 때 각 사실 문장에 단계, 주제, 말한 사람의 역할, 메시지 번호를 빠짐없이 적는다. "
    "같은 단계·주제에서 나중 메시지가 이전 결정을 바꾸면 이전 결정은 더 이상 유효하지 않은 것으로 본다. "
    "단계나 주제가 다른 결정은 서로 모순이 아니다."
)


class GraphitiGMB:
    def __init__(self, tuned: bool = False, k: int = 10):
        from graphiti_core import Graphiti

        self.tuned = tuned
        self.name = "graphiti_tuned" if tuned else "graphiti"
        self.k = k
        self.g = Graphiti(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                          os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "password"))
        self.group_id = f"gmb_{self.name}_{datetime.now():%Y%m%d_%H%M%S}"
        self.episode_to_msg: dict[str, str] = {}
        self.loop = asyncio.new_event_loop()
        self.ingest_minutes = 0.0

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def ingest(self, msgs: list[dict]) -> None:
        from graphiti_core.nodes import EpisodeType

        self._run(self.g.build_indices_and_constraints())
        extra = ({"edge_types": {"ChannelFact": ChannelFact}, "custom_extraction_instructions": TUNED_INSTRUCTIONS}
                 if self.tuned else {})
        ordered = sorted(msgs, key=lambda m: m["timestamp"])
        start = time.time()
        for i, m in enumerate(ordered, 1):
            for attempt in range(4):
                try:
                    res = self._run(self.g.add_episode(
                        name=m["msg_node"], episode_body=format_passage(m), source=EpisodeType.text,
                        source_description="team channel message", group_id=self.group_id,
                        reference_time=datetime.fromisoformat(m["timestamp"]).replace(tzinfo=timezone.utc), **extra))
                    break
                except Exception as e:  # 속도 제한 등 일시 오류는 기다렸다가 다시 시도
                    if attempt == 3:
                        raise
                    print(f"  [{self.name}] {m['msg_node']} 실패({type(e).__name__}), {10 * 2 ** attempt}초 후 재시도",
                          flush=True)
                    time.sleep(10 * 2 ** attempt)
            self.episode_to_msg[res.episode.uuid] = m["msg_node"]
            el = time.time() - start
            if i % 5 == 0 or i == len(ordered):
                print(f"  [{self.name}] {i}/{len(ordered)} (경과 {el / 60:.1f}분, 남은 예상 {el / i * (len(ordered) - i) / 60:.1f}분)",
                      flush=True)
        self.ingest_minutes = (time.time() - start) / 60

    def retrieve(self, question: str, asker: str) -> tuple[list[str], list[str]]:
        edges = self._run(self.g.search(query_text(question, asker), group_ids=[self.group_id], num_results=self.k))
        valid = [e for e in edges if e.invalid_at is None and e.expired_at is None]
        passages, ids = [], []
        for e in valid:
            src = [self.episode_to_msg[ep] for ep in e.episodes if ep in self.episode_to_msg]
            ids += [s for s in src if s not in ids]
            line = f"[fact / from={','.join(src) or '?'} / valid_at={e.valid_at}]\n{e.fact}"
            attrs = {k: v for k, v in (e.attributes or {}).items() if v not in (None, "")}
            if self.tuned and attrs:
                line += "\n(" + ", ".join(f"{k}={v}" for k, v in sorted(attrs.items())) + ")"
            passages.append(line)
        return passages, ids

    def close(self) -> None:
        self._run(self.g.close())
        self.loop.close()
