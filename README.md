# knowledge_harness

**Evidence-Bounded Knowledge Harness** — 데이터분석캡스톤디자인, TEAM YUSINESS (박재원, 정시찬)

## 지식 기반 팀 실험 시스템

공유된 문장이라는 이유만으로 근거의 강도나 승인 범위가 늘어나면 안 된다.
이 하네스는 각자의 AI와 팀 기록 사이에 들어가서 다음 두 가지를 한다.

- 주장을 올릴 때 조건·작성 주체·근거를 붙여 기록한다.
- 팀 주장으로의 승격(합의)을 별도 상태로 관리한다.

질문이 들어오면 **답할 수 있는 부분과 없는 부분을 구분해서** 답한다.

## 모듈 구성

```mermaid
flowchart LR
  subgraph 기록 입력
    A[새 기록] --> S[구조화<br/>작은 모델]
    S --> V[인용 검증<br/>규칙 → 애매하면 큰 모델]
    V --> G[PII 차단<br/>정규식 → 이름 등은 작은 모델]
    G --> J[관계 판정<br/>none / 조건 다름 / 재인용 / 지지 / 충돌]
    J --> DB[(팀 기록 저장소<br/>후보 / 승인)]
  end
  subgraph 질문 응답
    Q[질문] --> P[질문 파싱<br/>작은 모델]
    P --> R[리트리버<br/>topic → BM25]
    DB --> R
    R --> C[답변 구성<br/>조건 필터 · 상태 판정 · 근거 중복 제거]
    C --> O[답변 + 상태 + 근거 + 안내]
  end
```

| 모듈 | 파일 | 입력 → 출력 | 모델 |
|---|---|---|---|
| 구조화 | `harness/llm.py` `structure_record` | 자유 텍스트 기록 → topic·value·conditions·quote | 작은 모델 (선택) |
| 인용 검증 | `harness/verifier.py` | 근거(원문·버전·구간) → 맞음/틀림 | 규칙 기반 + 애매 구간만 큰 모델 |
| PII 차단 | `harness/pii.py` | 기록 → 민감 정보를 가린 공유용 사본 | 정규식 + 형식 없는 정보는 작은 모델 (선택) |
| 관계 판정 | `harness/relation.py` | 새 기록 + 기존 기록 → 관계 | 규칙 기반 |
| 저장소 | `harness/store.py` | 기록 → 저장, 충돌 시 검토 요청 표시 | - |
| 리트리버 | `harness/retriever.py` | 질문 → 후보 기록 | BM25 (임베딩으로 교체 가능) |
| 답변 구성 | `harness/answer.py` | 질문 + 후보 → 상태·근거·안내 | 템플릿 (LLM 문장화는 TODO) |

자세한 설계는 [docs/design.md](docs/design.md)를, 일정은 [docs/timeline.md](docs/timeline.md)를 참고한다.

## 실행

외부 의존성 없이 Python 3.10 이상에서 바로 돌아간다.

```bash
python -m eval.run_eval -v      # 하네스 vs 약한 베이스라인 + ablation, 질문별 답변 출력
python -m pytest -q tests       # 모듈 단위 테스트 (pytest 필요)
```

LLM 베이스라인과 Graphiti 베이스라인은 추가 설치가 필요하다. 가상환경 안에 설치한다.

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m eval.run_eval --systems harness,full_context_llm   # ANTHROPIC_API_KEY 필요
python -m eval.run_eval --systems harness,graphiti           # Neo4j + OPENAI_API_KEY 필요
```

Graphiti는 Neo4j 접속 정보를 환경변수(`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`)로 받는다.
본 실험 전에 `python -m scripts.graphiti_smoke`로 연결을 확인한다.

결과는 `results/<system>.json`에 질문별로 저장된다.

## 현재 결과 (합성 데이터 14문항)

스트롱 베이스라인은 **Graphiti**로 확정했다. 아래 표에는 아직 Graphiti 결과가 없다(실행 전).

| system | condition_match ↑ | status_acc ↑ | overgeneralization ↓ | false_consensus ↓ | bad_citation_used ↓ | evidence_error ↓ | pii_leak ↓ |
|---|---|---|---|---|---|---|---|
| retrieval_only (약한 베이스라인) | 0.00 | 0.43 | 0.93 | 1.00 | 0.14 | 2.21 | 0.14 |
| **harness** | **1.00** | **1.00** | **0.00** | **0.00** | **0.00** | **0.00** | **0.00** |
| harness − 조건 비교 | 0.29 | 0.36 | 0.71 | 0.00 | 0.00 | 1.00 | 0.00 |
| harness − 인용 검증 | 0.93 | 0.93 | 0.00 | 0.00 | 0.07 | 0.07 | 0.00 |
| harness − 재인용 묶기 | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.21 | 0.00 |
| harness − 승인 상태 | 0.79 | 0.79 | 0.00 | 0.36 | 0.00 | 0.00 | 0.00 |
| harness − PII 차단 | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.14 |

> **주의.** 이 데이터는 모듈이 제대로 도는지 보려고 직접 만든 시나리오다. 하네스의 규칙이 이 시나리오를 알고 만들어졌으므로 1.00은 성능 주장이 아니다.
> 이 표가 보여주는 것은 두 가지다. 하나는 각 모듈을 끄면 어느 메트릭이 나빠지는지다.
> 다른 하나는 메트릭이 실제로 차이를 잡아내는지다.
> 성능 비교는 Graphiti와 전체 맥락 LLM 베이스라인을 더 크고 현실적인 데이터에 돌려서 해야 한다.
> 해당 데이터는 [docs/design.md](docs/design.md)의 "평가 데이터 확장"을 참고한다.

## 디렉터리

```
harness/      하네스 모듈
baselines/    retrieval_only(약한), full_context_llm(LLM에 표로 넣기), graphiti(스트롱)
eval/         메트릭과 평가 스크립트
data/         sources/(실험 원문), records.json(팀 기록), queries.json(질문 + 정답)
docs/         설계, 일정
tests/        단위 테스트
```
