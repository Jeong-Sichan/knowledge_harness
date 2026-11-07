"""D12 저장소. 모든 객체의 id는 내용 해시이고, 한번 쓰면 고치지 않는다.

Store는 메모리에만 두고 FileStore는 객체마다 파일 하나로 남긴다. 같은 인터페이스라 나중에 DB로 바꿀 수 있다.
Git 동기화와 members.json은 아직 없다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from .model import Claim, Evidence, Source, Vote, apply_aliases


def content_id(prefix: str, data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return f"{prefix}_{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:24]}"


class Store:
    def __init__(self):
        self.sources: dict[str, Source] = {}
        self.claims: dict[str, Claim] = {}
        self.votes: list[Vote] = []
        self.aliases: dict[str, dict[str, str]] = {"topic": {}, "key": {}}

    def _saved(self, folder: str, name: str, data: dict) -> None:
        """파일 저장소만 쓴다."""

    def latest_source(self, doc: str) -> Source | None:
        return max((source for source in self.sources.values() if source.doc == doc),
                   key=lambda source: source.rev, default=None)

    def add_source(self, doc: str, text: str, author: str, location: str | None = None,
                   created_at: str = "") -> tuple[Source, bool]:
        """(원문, 새로 저장했는가). 같은 문서 이름에 다른 내용이 오면 다음 버전이다."""
        latest = self.latest_source(doc)
        if latest is not None and latest.text == text:
            return latest, False
        source = Source("", doc, latest.rev + 1 if latest else 1, author, text, location, created_at)
        source = replace(source, id=content_id("src", asdict(source)))
        self.sources[source.id] = source
        self._saved("sources", source.id, asdict(source))
        return source, True

    def add_claim(self, claim: Claim) -> Claim:
        """id가 비어 있으면 내용으로 만든다."""
        if not claim.id:
            claim = replace(claim, id=content_id("clm", asdict(claim)))
        self.claims[claim.id] = claim
        self._saved("claims", claim.id, asdict(claim))
        return claim

    def add_vote(self, vote: Vote) -> None:
        self.votes.append(vote)
        self._saved("votes", content_id("vot", asdict(vote)), asdict(vote))

    def add_alias(self, kind: str, alias: str, of: str, by: str, at: str = "") -> None:
        self.aliases[kind][alias] = of
        data = {"alias": alias, "of": of, "kind": kind, "by": by, "at": at}
        self._saved("aliases", content_id("als", data), data)

    def all_claims(self) -> list[Claim]:
        return apply_aliases(list(self.claims.values()), self.aliases["topic"], self.aliases["key"])

    def topics(self) -> list[str]:
        return sorted({claim.topic for claim in self.all_claims()})

    def condition_keys(self) -> list[str]:
        return sorted({key for claim in self.all_claims() for key in claim.conditions})

    def latest_texts(self) -> dict[str, str]:
        return {doc: self.latest_source(doc).text for doc in {source.doc for source in self.sources.values()}}


class FileStore(Store):
    """team-records 폴더 구조로 저장한다. 시작할 때 기존 파일을 모두 읽는다."""

    def __init__(self, root: str | Path):
        super().__init__()
        self.root = Path(root)
        for data in self._read("sources"):
            self.sources[data["id"]] = Source(**data)
        for data in self._read("claims"):
            evidence = tuple(Evidence(**item) for item in data["evidence"])
            self.claims[data["id"]] = Claim(**{**data, "evidence": evidence, "seen": tuple(data["seen"])})
        self.votes = [Vote(**data) for data in self._read("votes")]
        for data in self._read("aliases"):
            self.aliases[data["kind"]][data["alias"]] = data["of"]

    def _read(self, folder: str) -> list[dict]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((self.root / folder).glob("*.json"))]

    def _saved(self, folder: str, name: str, data: dict) -> None:
        path = self.root / folder / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
