# 4편. 비교 대상과 평가 코드 해설

이 편에서는 하네스가 아닌 나머지 코드를 설명한다.

- `baselines/`: 비교 대상 (시험 보는 다른 학생들)
- `eval/`: 실험 실행과 채점 (감독관과 채점표)
- `scripts/`: 보조 도구
- `tests/`: 자동 테스트

3편 처음의 "파이썬 읽는 법"을 먼저 보고 오면 편하다. 코드는 읽기 쉽게 일부 줄이거나 주석을 덧붙인 곳이 있다.

---

## 1. `baselines/`: 비교 대상 세 가지

**왜 비교 대상이 필요한가?** "하네스가 좋다"고 말하려면 "무엇보다?"에 답해야 한다. 멘토가 강조한 것도 이 점이다. 그래서 세 가지와 비교한다.

| 비교 대상 | 비유 | 왜 골랐나 |
|---|---|---|
| 일반 검색 (`retrieval_only`) | 참고서에서 비슷한 단어가 나오는 쪽만 펴보는 학생 | 하네스 없이 흔히 하는 방식 (약한 베이스라인) |
| 전체 맥락 LLM (`full_context_llm`) | 참고서를 통째로 다 읽는 학생 | "정보를 그냥 다 넣어주면 되지 않나?"에 답하려고 |
| Graphiti (`graphiti_baseline`) | 참고서를 요약 노트(지식 그래프)로 정리해서 보는 학생 | 이미 있는 강한 도구 (스트롱 베이스라인) |

세 대상 모두 하네스와 **같은 답안지 양식(`Response`)**으로 답한다. llm 모드에서는 **같은 AI 답변기**까지 쓴다.

### 1-1. `retrieval_only.py`: 일반 검색

```python
class RetrievalOnly:
    name = "retrieval_only"

    def __init__(self, sources_dir=None, answerer="rule", k=None):
        self.answerer = answerer
        self.k = k or (5 if answerer == "llm" else 3)
        self.sources = SourceStore(sources_dir) if sources_dir else None
        self.records = []
```
- 검색 결과를 몇 개 가져올지(`k`) 정한다. AI 답변기를 쓸 때는 5개, 아니면 3개다.
- 5개로 늘린 이유는 AI에게 판단할 기회를 충분히 주려는 것이다.

```python
    def ingest(self, records):
        self.records = list(records)
```
- 기록을 그냥 목록에 담는다. **검사, 구조화, 관계 판정이 하나도 없다.** 이게 "하네스가 없을 때"다.

```python
    def ask(self, q):
        hits = bm25_top_k(self.records, q.question, self.k)
        if self.answerer == "llm":
            return answer_with_llm(q.question, raw_context(hits, self.sources))
        if not hits:
            return Response(NO_EVIDENCE, [], [], 0, answer="관련 기록이 없습니다.")
        ids = [r.id for r in hits]
        return Response(ANSWERED, ids, ids, len(hits),
                        answer=f"{hits[0].value} (관련 기록 {len(hits)}건)",
                        exposed=[r.text for r in hits])
```
- 질문과 단어가 겹치는 기록 상위 k개를 찾는다. 하네스와 **같은 BM25 함수**를 쓴다.
- **llm 모드:** 찾은 기록 원본과 원문을 공통 AI 답변기에 넘긴다.
- **rule 모드:** 찾은 걸 전부 근거이자 팀 사실로 내놓고, 개수를 그대로 근거 수로 센다. 조건도 승인도 재인용도 보지 않는 "순진한" 방식이다.

### 1-2. `full_context_llm.py`: 전부 넣기

```python
class FullContextLLM:
    name = "full_context_llm"

    def __init__(self, sources_dir):
        self.sources = SourceStore(sources_dir)
        self.context = []

    def ingest(self, records):
        self.context = raw_context(sorted(records, key=lambda r: r.created_at), self.sources)

    def ask(self, q):
        return answer_with_llm(q.question, self.context)
```
- 기록 **전부**와 원문 **전부**를 하나로 이어 붙여 두었다가, 질문마다 통째로 AI에게 넘긴다.
- AI는 판단에 필요한 정보(작성자, 승인 상태, 인용, 원문의 조건)를 **모두 본다.** 그래서 정확도는 높을 수 있다.
- 대신 기록이 늘면 넘기는 글이 끝없이 길어진다. 민감 정보도 매번 전부 넘어간다.

### 1-3. `graphiti_baseline.py`: Graphiti

Graphiti는 다른 회사(Zep)가 만든 오픈소스다. 우리는 그걸 **불러다 쓰는 연결 코드(어댑터)**를 만들었다.

```python
KST = timezone(timedelta(hours=9))
```
- 한국 시간대다. 기록 작성 시각을 Graphiti에 넘길 때 쓴다.

```python
    def __init__(self, sources_dir, answerer="rule", k=5, graphiti=None, group_id=None):
        if graphiti is None:
            from graphiti_core import Graphiti
            graphiti = Graphiti(os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                                os.environ.get("NEO4J_USER", "neo4j"),
                                os.environ.get("NEO4J_PASSWORD", "password"))
        self.g = graphiti
        ...
        self.group_id = group_id or f"harness_eval_{datetime.now():%Y%m%d_%H%M%S}"
        self.episode_to_record = {}
        self.loop = asyncio.new_event_loop()
```
- Neo4j(그래프 저장소)에 접속한다. 주소와 비밀번호는 환경변수에서 읽는다.
- `group_id`: **실행할 때마다 새 이름표**를 만든다. 예: `harness_eval_20261030_153012`. 지난번 실행에서 넣은 데이터가 이번 결과에 섞이지 않게 하려는 것이다.
- `episode_to_record`: Graphiti 내부 번호 → 우리 기록 번호(R01 등) 대응표. 채점하려면 Graphiti가 어느 기록을 근거로 썼는지 알아야 한다.
- `asyncio`: Graphiti는 "비동기" 방식으로 동작한다. 여러 일을 동시에 처리하는 방식인데, 우리 코드는 순서대로 동작하니 `_run`으로 감싸서 하나씩 기다린다.

```python
    def ingest(self, records):
        self._run(self.g.build_indices_and_constraints())
        ordered = sorted(records, key=lambda r: r.created_at)
        start = time.time()
        for i, r in enumerate(ordered, 1):
            body = "\n".join(raw_context([r], self.sources))
            for attempt in range(4):
                try:
                    result = self._run(self.g.add_episode(
                        name=r.id, episode_body=body, source=EpisodeType.text,
                        source_description="team record", group_id=self.group_id,
                        reference_time=datetime.fromisoformat(r.created_at).replace(tzinfo=KST)))
                    break
                except Exception as e:
                    if attempt == 3:
                        raise
                    wait = 10 * 2 ** attempt
                    print(f"  [graphiti] {r.id} 실패({type(e).__name__}), {wait}초 후 재시도", flush=True)
                    time.sleep(wait)
            self.episode_to_record[result.episode.uuid] = r.id
            ...
            print(f"  [graphiti] {i}/{len(ordered)} {r.id}: 사실 {len(result.edges)}개 (경과 ..., 남은 예상 ...)")
```
- 기록을 시간 순서대로 하나씩 Graphiti에 "에피소드"로 넣는다.
- **다른 시스템과 같은 재료**(기록 원본 + 원문)를 넣는다. 공정성을 위해서다.
- Graphiti는 에피소드를 받을 때마다 AI를 여러 번 불러서 **사실(edge)**을 뽑는다. 예: "정시찬은 XGBoost를 가장 좋은 모델로 평가했다." 그래서 느리다. 기록 115개에 24분이 걸렸다.
- 일시적인 오류(예: 너무 자주 요청해서 거절됨)가 나면 10초, 20초, 40초 기다렸다가 다시 시도한다. 4번째에도 실패하면 멈춘다.
- 진행 상황과 남은 예상 시간을 출력한다.

```python
    def ask(self, q):
        edges = self._run(self.g.search(q.question, group_ids=[self.group_id], num_results=self.k))
        valid = [e for e in edges if e.invalid_at is None and e.expired_at is None]
        if self.answerer == "llm":
            context = [f"[{','.join(self._record_ids([e])) or '출처 불명'}] {e.fact}" for e in valid]
            return answer_with_llm(q.question, context)
        ...
```
- 질문으로 Graphiti를 검색해서 관련 사실 5개를 받는다.
- Graphiti가 **무효 처리한 사실**(새 정보 때문에 더는 맞지 않다고 판단한 것)은 뺀다.
- llm 모드에서는 사실마다 출처 기록 번호를 붙여서 공통 AI 답변기에 넘긴다. 예: `[R01] 정시찬은 XGBoost를 가장 좋은 모델로 평가했다`
- **여기서 문제가 드러났다.** Graphiti가 만든 사실 문장에는 조건(피처 12개, v1)과 승인 상태가 대부분 빠져 있다. 그래서 AI가 판단을 못 했다(5편).

```python
    def _record_ids(self, edges):
        ...  # 사실(edge)이 나온 에피소드 번호를 우리 기록 번호로 바꾼다

    def invalidated_facts(self):
        edges = self._run(self.g.search("모델 피처 데이터 결측치 불균형", group_ids=[self.group_id], num_results=50))
        return [(e.fact, str(e.invalid_at or e.expired_at)) for e in edges
                if e.invalid_at is not None or e.expired_at is not None]

    def close(self):
        ...
```
- `invalidated_facts`: Graphiti가 무효 처리한 사실 목록을 뽑는다. 1차 실험에서 "올바른 0.05가 틀린 0.1 때문에 무효화된" 사례를 이걸로 찾았다.
- `close`: 실험이 끝나면 Neo4j 연결을 닫는다.

---

## 2. `eval/`: 실험 실행과 채점

### 2-1. `metrics.py`: 채점 기준표

답안지(`Response`) 하나를 정답과 비교해서 점수를 매긴다.

```python
@dataclass
class QueryScore:
    qid: str
    status_ok: bool
    overgeneralization: bool
    false_consensus: bool
    bad_citation_used: bool
    irrelevant_used: bool
    evidence_error: int
    pii_in_context: bool
    pii_in_answer: bool
    context_chars: int

    @property
    def condition_match(self):
        return (self.status_ok and not self.overgeneralization
                and not self.bad_citation_used and not self.irrelevant_used)
```
- 질문 하나의 채점 결과다. 각 항목은 아래 표에 정리했다.
- **메인 점수 `condition_match`(조건 일치 답변):** 아래 네 가지를 **모두** 만족해야 1점이다.
  1. 상태가 맞음
  2. 조건이 다른 기록을 근거로 쓰지 않음
  3. 틀린 인용을 쓰지 않음
  4. 주제가 다른 기록을 쓰지 않음

```python
def score_query(gold, resp, records):
    cond = gold["conditions"]
    context = " ".join(resp.exposed)
    shown = " ".join([resp.answer, *resp.notes])
    secrets = [s for r in records.values() for s in r.get("_gold_pii", [])]
    used = [records[i] for i in resp.supporting_ids if i in records]
    facts = [records[i] for i in resp.team_fact_ids if i in records]
```
- 채점 준비를 한다.
  - `context`: AI에게 넘어간 글 전체
  - `shown`: 사용자에게 보인 답과 안내
  - `secrets`: 민감 정보 정답 목록 (전화번호, 이메일, 실명, API 키)
  - `used`: 근거로 쓴 기록
  - `facts`: 팀 사실이라고 말한 기록
- **채점에는 records.json의 정답 칸을 쓴다.** 시스템이 스스로 판단한 조건이 아니라 정답 조건으로 채점한다.

```python
    return QueryScore(
        qid=gold["id"],
        status_ok=resp.status == gold["expected_status"],
        overgeneralization=any(r["topic"] == gold["topic"] and not is_compatible(cond, r.get("conditions", {}))
                               for r in used),
        false_consensus=any(r.get("status") != APPROVED for r in facts),
        bad_citation_used=any(r.get("_gold_citation_valid") is False for r in used),
        irrelevant_used=any(r["topic"] != gold["topic"] for r in used),
        evidence_error=abs(resp.independent_evidence - gold["expected_independent_evidence"]),
        pii_in_context=any(s in context for s in secrets),
        pii_in_answer=any(s in shown for s in secrets),
        context_chars=len(context),
    )
```

| 항목 | 뜻 | 좋은 방향 | 예 |
|---|---|---|---|
| `status_ok` | 상태(4가지)를 맞혔나 | 높을수록 | Q02에 "충돌"이라고 했나 |
| `overgeneralization` (과잉 일반화) | 같은 주제인데 **조건이 다른** 기록을 근거로 썼나 | 낮을수록 | 피처 40개 질문에 피처 12개 기록을 씀 |
| `irrelevant_used` | **주제가 다른** 기록을 근거로 썼나 | 낮을수록 | 모델 질문에 결측치 기록을 씀 (검색 실수) |
| `false_consensus` (잘못된 합의) | 승인 안 된 기록을 **팀 사실**이라고 했나 | 낮을수록 | AI가 올린 R04를 팀 사실로 제시 |
| `bad_citation_used` | 틀린 인용(R08)을 근거로 썼나 | 낮을수록 | |
| `evidence_error` | 독립 근거 수가 정답과 몇 개 다른가 | 낮을수록 | Q07에 "근거 3개"라고 하면 오차 2 |
| `pii_in_context` | AI에게 넘긴 글에 민감 정보가 있었나 | 낮을수록 | |
| `pii_in_answer` | 사용자에게 보인 답에 민감 정보가 있었나 | 낮을수록 | "대표 사례는 김민수(010-…)" |
| `context_chars` | AI에게 넘긴 글자 수 | 낮을수록 (비용·속도) | |

```python
def summarize(scores):
    n = max(1, len(scores))
    rate = lambda f: sum(map(f, scores)) / n
    return {"condition_match": rate(lambda s: s.condition_match), ... }
```
- 질문 14개의 점수를 **평균**한다. 참/거짓 항목은 "참인 비율"이 된다. 예: 14개 중 13개 맞으면 0.93.

### 2-2. `run_eval.py`: 시험 감독관 (실험 시작점)

명령어 `python -m eval.run_eval ...`로 실행하는 파일이다.

```python
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```
- 한국어 Windows 터미널(cp949)에서 한글이나 기호를 출력하다 프로그램이 멈추지 않게 하는 설정이다.

```python
ABLATIONS = {
    "harness-no_conditions": {"cfg": ComposerConfig(use_conditions=False)},
    "harness-no_verifier": {"cfg": ComposerConfig(use_verifier=False)},
    "harness-no_dedup": {"cfg": ComposerConfig(use_dedup=False)},
    "harness-no_approval": {"cfg": ComposerConfig(use_approval=False)},
    "harness-no_pii": {"use_pii": False},
}
```
- **모듈 끄기 실험** 목록이다. 하네스에서 부품을 하나씩 뺀 버전 5개다.

```python
def build(name, answerer, src=DATA / "sources"):
    structure = "llm" if answerer == "llm" else "gold"
    if name == "harness":
        return Harness(src, structure=structure, answerer=answerer)
    ...
```
- 이름을 받아서 시스템(학생)을 만든다. llm 모드면 하네스도 직접 구조화하도록(`structure="llm"`) 만든다.

```python
def report_structuring(name, system, gold):
    recs = system.store.records
    cond_ok = sum(recs[i].conditions == gold[i]["conditions"] for i in recs)
    ...
    print(f"[{name}] 구조화 정확도: 조건 {cond_ok}/{len(ids)}, 주제 묶음(쌍 기준) {topic_ok}/{len(pairs)}")
```
- llm 모드에서 하네스가 기록의 조건을 **정답과 똑같이** 뽑았는지 센다.
- **주제 묶음:** AI가 지은 주제 이름은 정답과 다를 수 있다(예: best_model 대신 model_choice). 그래서 이름 대신 **"같은 주제끼리 같이 묶였나"**를 기록 두 개씩 짝지어 확인한다.
- 하네스가 틀렸을 때 구조화 단계에서 틀렸는지 가려내는 용도다.

```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="retrieval_only,harness")
    ap.add_argument("--answerer", choices=["rule", "llm"], default="rule")
    ap.add_argument("--scale", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "results"))
```
명령어 옵션은 다음과 같다.

| 옵션 | 뜻 |
|---|---|
| `--systems` | 비교할 시스템. 쉼표로 구분 |
| `--answerer` | `rule`(템플릿) 또는 `llm`(공정 비교) |
| `--scale N` | 방해 기록 N개를 섞는다 |
| `--seed` | 방해 기록을 만들 때 쓰는 난수 씨앗. 같은 숫자면 같은 기록이 생긴다 |
| `--no-ablation` | 모듈 끄기 실험을 생략한다 |
| `-v` | 질문별 답변까지 출력한다 |
| `--out` | 결과 저장 폴더 |

```python
    if args.scale:
        raw_records, src = build_scaled_dataset(args.scale, args.seed)
    else:
        raw_records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    gold_queries = json.loads((DATA / "queries.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw_records}
```
- 기록과 질문을 읽는다. `--scale`이면 방해 기록을 섞은 데이터를 쓴다.

```python
    for name in names:
        system = build(name, args.answerer, src)
        system.ingest([Record.from_dict(r) for r in raw_records])
        if llm_mode and hasattr(system, "store"):
            report_structuring(name, system, by_id)
        for g in gold_queries:
            q = Query(g["id"], g["question"]) if llm_mode else Query.from_dict(g)
            resp = system.ask(q)
            s = score_query(g, resp, by_id)
            ...
```
- **실험의 심장부**다. 시스템마다 다음을 반복한다.
  1. 만든다
  2. 기록을 전부 넣는다 (`ingest`)
  3. 질문을 하나씩 던진다 (`ask`)
  4. 채점한다 (`score_query`)
- **llm 모드에서는 질문 문장만 준다**(`Query(id, question)`). 정답 주제와 조건은 채점에만 쓴다.

```python
        summary = summarize(scores)
        (out_dir / f"{name}{suffix}.json").write_text(json.dumps({"summary": summary, "details": details}, ...))
        ...
    print("\n| system | " + " | ".join(cols) + " |")
    ...
```
- 시스템별 평균 점수를 내고, 질문별 상세 결과를 `results/이름.json`에 저장한다.
- 마지막에 결과 표를 출력한다. 우리가 지금까지 본 표가 이것이다.

### 2-3. `scale.py`: 방해 기록 만들기

```python
FEATURES = [8, 16, 20, 24, 30, 50, 64]
DATASETS = ["v4", "v5", "v6", "v7"]
```
- 방해 기록에 쓸 조건이다. 질문이 묻는 조건(피처 12·40개, v1·v2·v3)과 **절대 겹치지 않게** 골랐다.

```python
TOPICS = {
    "best_model": (["XGBoost", "LightGBM", "CatBoost", "RandomForest"],
                   "이탈 예측 모델은 {v}가 가장 좋았다.", "{v} AUC 0.8{r}", True, "이탈 예측 모델 비교"),
    ...
}
```
- 주제마다 다섯 가지를 정해 두었다.
  1. 값 후보
  2. 주장 문장 틀
  3. 원문 결과 문장 틀 (이게 인용이 된다)
  4. 피처 수 조건을 넣을지
  5. 문서 제목
- 진짜 기록과 **문장이 비슷해서** 단어 검색이 헷갈리기 쉽다.

```python
def make_distractors(n, seed=0):
    rng = random.Random(seed)
    for i in range(n):
        topic = topics[i % len(topics)]
        ...
        v = rng.choice(values)
        cond = {"dataset": rng.choice(DATASETS)}
        if with_features:
            cond["n_features"] = rng.choice(FEATURES)
        ...
        sources[sid] = (f"# {sid} — {title} ...\n- 조건: {cond_line}\n\n## 결과\n{quote}.\n")
        records.append({"id": f"D{i:04d}", ...})
    return records, sources
```
- 주제를 돌아가며 고르고, 값·조건·작성자·승인 여부를 무작위로 정해서 기록과 원문을 만든다.
- `random.Random(seed)`: 같은 seed면 **매번 같은 기록**이 나온다. 그래서 실험을 다시 해도 결과를 비교할 수 있다.

```python
def build_scaled_dataset(n, seed=0):
    base = json.loads((ROOT / "data" / "records.json").read_text(encoding="utf-8"))
    extra, extra_sources = make_distractors(n, seed)
    out = ROOT / ".cache" / f"scale_{n}_seed{seed}" / "sources"
    ...
    return base + extra, out
```
- 원래 기록 15개에 방해 기록을 더하고, 원문 폴더를 `.cache/` 아래에 만든다.

---

## 3. `scripts/`: 보조 도구

| 파일 | 하는 일 | 실행 |
|---|---|---|
| `graphiti_smoke.py` | Neo4j 접속 → 에피소드 1개 넣기 → 검색, 세 단계가 되는지 확인한다. 본 실험 전에 연결이 잘 되는지 보는 용도 | `python -m scripts.graphiti_smoke` |
| `plot_scale.py` | 규모 실험 결과로 그래프(`docs/figures/context_vs_records.svg`)를 그린다. 외부 도구 없이 SVG 그림 파일을 직접 쓴다 | `python -m scripts.plot_scale` |

`plot_scale.py`에서 알아둘 점은 이렇다.
- 값은 실험 기록(`docs/experiments.md`)에서 옮겨 적었다. 새 실험을 하면 파일 위쪽 `SERIES`의 숫자를 바꾸고 다시 실행하면 된다.
- y축은 **로그 축**이다. 330과 87,026처럼 차이가 큰 값을 한 그림에 보여주려고 칸마다 10배씩 늘어나게 했다.
- 색은 색약인 사람도 구분되는지 검사 도구로 확인했다. 색만으로 구분하지 않도록 마커 모양(●■▲)도 다르게 했다.

---

## 4. `tests/test_harness.py`: 자동 테스트 12개

코드를 고친 뒤 `python -m pytest -q tests`를 실행하면 아래 12가지를 자동으로 확인한다. 하나라도 실패하면 뭔가 망가진 것이다.

| 테스트 | 확인하는 것 |
|---|---|
| `test_relations_follow_table` | R02 = 재인용, R03 = 조건 다름, R04 = 충돌로 판정되나 |
| `test_conflict_keeps_both_and_requests_review` | 충돌하면 양쪽 다 남기고 둘 다 "검토 필요"가 되나 |
| `test_verifier_rejects_changed_number` | R07은 통과, R08(숫자만 바뀜)은 탈락하나 |
| `test_condition_gap_is_reported` | 피처 40개 질문에 "근거 없음"이라고 답하나 |
| `test_recitation_not_counted_as_independent` | 재인용 3건을 독립 근거 1개로 세나 |
| `test_unapproved_is_not_team_fact` | 승인 전 후보를 팀 사실로 내놓지 않나 |
| `test_answer_cache_invalidated_by_new_record` | 새 기록이 들어오면 답변 캐시가 새로 계산되나 |
| `test_pii_masked_before_sharing` | 전화번호·이메일·키가 가려지나, 인용 검증은 가리기 전에 하나 |
| `test_pii_guard_ignores_normal_numbers` | AUC 0.842 같은 일반 숫자는 가리지 않나 |
| `test_graphiti_adapter_maps_episodes_to_records` | 가짜 Graphiti로 어댑터가 기록 번호를 제대로 찾나 (Neo4j 없이) |
| `test_llm_mode_plumbing_without_api` | 가짜 AI로 llm 모드 전체 흐름이 도나, **외부 AI로 나가는 글에 민감 정보가 없나** |
| `test_scale_distractors_keep_gold_valid` | 방해 기록이 정답을 바꾸지 않나, 인용이 원문과 맞나 |

**가짜(fake) 객체란?** 진짜 Graphiti나 AI를 부르려면 서버와 돈이 필요하다. 그래서 테스트할 때는 "정해진 답을 돌려주는 가짜"를 대신 끼운다. 이렇게 하면 우리 코드의 연결 부분이 맞는지만 빠르게 확인할 수 있다.

---

## 5. 그 밖의 파일

| 파일 | 하는 일 |
|---|---|
| `requirements.txt` | 설치할 외부 패키지 목록. `anthropic`(Claude), `pydantic`(답 양식 검사), `graphiti-core`(Graphiti), `httpx`(Graphiti가 쓰는데 스스로 설치하지 않는 패키지), `pytest`(테스트). OpenAI 패키지는 graphiti-core가 함께 설치한다 |
| `.gitignore` | git에 올리지 않을 것: 캐시(`.cache/`), 결과(`results/`), 가상환경(`.venv/`), 비밀키 파일(`.env`) |
| `.cache/` (자동 생성) | AI 응답 캐시, 규모 실험용 원문 |
| `results/` (자동 생성) | 실험 결과 JSON |

> **requirements.txt에 한글 주석이 없는 이유:** 한국어 Windows에서 pip가 이 파일을 cp949로 읽다가 한글 주석 때문에 실패한 적이 있다. 그래서 영어로만 쓴다.
