# Evidence-Bounded Knowledge Harness v2

팀원의 AI가 팀 기록을 쓰고 읽을 때, **근거가 허용하는 범위 안에서만** 쓰고 답하게 만드는 검문소입니다.
2~6명이 데이터 분석·ML 실험을 함께 하는 팀을 대상으로 합니다. 데이터 분석 캡스톤디자인, 팀 YUSINESS.

이 `test` 브랜치에는 v2 모듈과 그 테스트, 측정 코드만 담았습니다. 이전 하네스, 비교 시스템, 데모는 `main` 브랜치에 있습니다.
모든 설계 판단은 [docs/design_v2.md](docs/design_v2.md)의 결정 D1~D15를 따릅니다.

## 막으려는 실패

| # | 실패 | 예 | 막는 모듈 |
|---|---|---|---|
| 1 | 조건을 넘는 일반화 | 피처 12개 결과를 40개 질문의 답으로 씀 | `conditions`, `ask` |
| 2 | 미승인 후보를 팀 사실처럼 말함 | 작성자가 확인 안 한 AI 추출 결과를 사실로 답함 | `approval`, `ask` |
| 3 | 재인용을 독립 근거로 셈 | 같은 실험 하나를 근거 3개처럼 말함 | `relations` |
| 4 | 틀린 인용을 근거로 씀 | 원문은 0.05인데 0.1로 인용 | `quote`, `structure` |
| 5 | 바뀐 결정을 모르고 옛 결정으로 답함 | 대체된 결정을 현재 결정으로 답함 | `relations`, `approval` |

## 지금 상태

| 구분 | 상태 |
|---|---|
| 규칙 모듈과 LLM 모듈 | 구현됨. 테스트 138개 통과 (서버 없이 돌아감) |
| 전체 흐름 (글 올리기 → 질문 → 답 검사) | 파이썬 함수로 연결됨. 실제 모델로 QA20 20문항까지 돌림 |
| MCP 서버 (D13) | **없음.** 도구 4개가 아직 외부에 열려 있지 않음 |
| 승인 화면 (D7) | **없음.** 승인은 코드에서 투표 객체를 넣어 시험함 |
| Git 자동 동기화와 `members.json` (D12) | **없음.** 파일 저장까지만 구현됨 |
| `my_inbox` (D13) | **없음** |
| 시험용 측정, 사람 판정 | **아직 안 함.** 아래 결과는 전부 개발용 |

## 폴더 구조

```text
├── README.md
├── requirements.txt       httpx, pytest
├── docs/design_v2.md      설계 결정 D1~D15
├── harness_v2/            모듈 하나가 파일 하나
├── eval/                  측정 실행기 (데이터는 없음)
└── tests/                 서버 없이 도는 테스트
```

## 모듈

파일을 아래 순서대로 읽으면 앞 모듈만 알아도 다음 모듈을 이해할 수 있습니다. 커밋도 같은 순서로 쌓았습니다.

### 규칙 모듈: LLM을 쓰지 않습니다

같은 입력에는 항상 같은 결과가 나오고, 정답이 정해진 테스트로 확인합니다.

| 모듈 | 결정 | 하는 일 | 테스트 |
|---|---|---|---|
| [`model.py`](harness_v2/model.py) | D2 | 원문, 주장, 투표, 별칭의 모양을 정합니다. 상태와 관계는 저장하지 않습니다 | `test_v2_rules.py` |
| [`conditions.py`](harness_v2/conditions.py) | D5 | 질문의 조건과 주장의 조건을 비교합니다. 결과는 일치, 미확인, 불일치입니다 | `-k d5` |
| [`relations.py`](harness_v2/relations.py) | D6, D12 ③ | 두 주장이 재인용, 정정, 지지, 충돌 등 어떤 관계인지와 앞뒤 순서를 판정합니다 | `-k "d6 or d12"` |
| [`approval.py`](harness_v2/approval.py) | D7 | 투표와 관계로 승인, 거절, 대체, 정정 상태를 매번 계산합니다 | `-k d7` |
| [`quote.py`](harness_v2/quote.py) | D3 | 인용이 원문에 글자 그대로 있는지 봅니다. 공백 차이만 허용합니다 | `test_v2_quote.py` |
| [`ask.py`](harness_v2/ask.py) | D8 ②~④ | 주제 하나의 주장을 거르고 답변 상태를 정합니다 | `-k d8` |
| [`pii.py`](harness_v2/pii.py) | D11 | 전화번호, 이메일, 주민번호, API 키를 정규식으로 가립니다 | `test_v2_flow.py` |
| [`store.py`](harness_v2/store.py) | D12 | 내용 해시를 id로 저장하고 고치지 않습니다. 메모리와 파일 저장소가 있습니다 | `test_v2_flow.py` |

`-k`는 아래처럼 [`tests/test_v2_rules.py`](tests/test_v2_rules.py)에서 그 모듈 부분만 고르는 옵션입니다.

```bash
python -m pytest tests/test_v2_rules.py -k d5
```

### LLM 모듈: 서버 모델을 부릅니다

의미를 읽는 일만 모델에게 맡기고, 결과는 규칙으로 다시 검사합니다.

| 모듈 | 결정 | 하는 일 | 테스트 |
|---|---|---|---|
| [`llm.py`](harness_v2/llm.py) | D14 | vLLM 서버에 묻고 JSON을 받습니다. 모든 호출을 파일에 남겨 서버 없이 다시 돌릴 수 있습니다 | `test_v2_layer1.py` |
| [`structure.py`](harness_v2/structure.py) | D4 | 자유 글에서 주장을 뽑습니다. 인용이 틀리면 최대 2번 다시 묻습니다 | `test_v2_layer1.py`, `test_v2_flow.py` |
| [`interpret.py`](harness_v2/interpret.py) | D8 ① | 질문에서 주제, 조건, 현재/이력을 뽑습니다 | `test_v2_public.py`, `test_v2_flow.py` |
| [`check.py`](harness_v2/check.py) | D9 | AI가 쓴 답을 검사합니다. 근거 번호와 민감 정보는 규칙, 상태별 체크리스트는 모델이 봅니다 | `test_v2_layer1.py` |

### 연결 모듈: 위 모듈을 잇습니다

| 모듈 | 결정 | 하는 일 | 테스트 |
|---|---|---|---|
| [`submit.py`](harness_v2/submit.py) | D13 `submit_note` | 민감 정보 가림 → 원문 저장 → 주장 추출 → 관계 계산 | `test_v2_flow.py` |
| [`respond.py`](harness_v2/respond.py) | D8 ⑤, D9 ① | 질문 해석 뒤 근거 번호, 답변 규칙, `safe_answer`가 담긴 응답을 만듭니다 | `test_v2_flow.py` |

`test_v2_flow.py`에는 D13의 시나리오 1~6(결정이 바뀌는 과정)이 들어 있습니다.

### 측정 코드

| 파일 | 결정 | 재는 것 | 테스트 |
|---|---|---|---|
| [`eval/layer1.py`](eval/layer1.py) | D15 | 인용, 답 검사 | `test_v2_layer1.py` |
| [`eval/public_data.py`](eval/public_data.py) | D15 | 공개 데이터를 측정용 JSONL로 변환 | `test_v2_public.py` |
| [`eval/layer1_public.py`](eval/layer1_public.py) | D15 | 주장 뽑기, 질문 해석, 관측/결정 분류 | `test_v2_public.py` |
| [`eval/qa20.py`](eval/qa20.py) | D15 | 팀원 QA20 패키지를 전체 흐름으로 실행 | `test_v2_qa20.py` |

## 동작 순서

**글을 올릴 때**

1. `pii`가 민감 정보를 가립니다.
2. `store`가 원문을 통째로 저장합니다.
3. `structure`가 주장을 뽑고 `quote`가 인용을 검사합니다.
4. `relations`가 기존 주장과의 관계를 계산합니다.
5. 사람이 승인하면 `approval`이 상태를 계산합니다. 승인 전에는 후보로만 남습니다.

**질문할 때**

1. `interpret`가 질문을 주제와 조건으로 바꿉니다.
2. `ask`가 그 주제의 주장을 전부 가져와 `conditions`와 `approval` 결과로 거릅니다.
3. `respond`가 근거 번호, 답변 규칙, `safe_answer`를 돌려줍니다.
4. 팀원의 AI가 답을 쓰고 `check`가 검사합니다. 하네스가 최종 답을 직접 쓰지는 않습니다.

답변 상태는 `answered`, `conflict`, `only_unapproved`, `no_evidence`, `by_condition`, `error` 중 하나입니다.

## 실행

Python 3.13에서 확인했습니다.

```bash
pip install -r requirements.txt
```

```bash
python -m pytest tests -q
```

테스트는 가짜 LLM을 쓰므로 GPU와 서버가 없어도 됩니다.

실제 모델을 쓰려면 vLLM 서버 주소를 환경변수로 줍니다.

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `HARNESS_V2_BASE_URL` | `http://127.0.0.1:8000/v1` | vLLM 주소. 쉼표로 여러 개를 주면 나눠 보냅니다 |
| `HARNESS_V2_MODEL` | `Qwen/Qwen3-8B` | 모델 이름 |
| `HARNESS_V2_THINKING` | 꺼짐 | `1`이면 추론 모드를 켭니다 |
| `HARNESS_V2_LOG` | `.cache/v2_calls.jsonl` | 호출 기록 파일이자 캐시 |

측정 명령은 아래와 같습니다. 괄호 안의 경로는 각자 데이터가 있는 곳입니다.

```bash
python -m eval.layer1 --data-root <datasets-v1> --split dev --out <결과.json>
```

```bash
python -m eval.public_data --measeval <폴더> --wikisql <폴더> --hibernate <decisions.xlsx> --out <폴더>
```

```bash
python -m eval.layer1_public --data <폴더> --split dev --out <결과.json>
```

```bash
python -m eval.qa20 --data <qa20 폴더> --out <결과 폴더>
```

측정에 쓴 환경은 vLLM `0.8.5.post1`, `Qwen/Qwen3-8B` BF16, RTX 3090, temperature 0, 입력 길이 16,384입니다.
추론 모드는 vLLM V0 엔진(`VLLM_USE_V1=0`)에 `--enable-reasoning --reasoning-parser deepseek_r1 --guided-decoding-backend xgrammar --enforce-eager`로 켰습니다.

## 지금까지의 측정 결과

모두 개발용 데이터 결과이고, 최종 점수가 아닙니다. 정답 개수로 보고하며 신뢰구간은 내지 않습니다.

| 부품 | 결과 | 비고 |
|---|---|---|
| 인용 (재시도 후) | 248/253 (98.0%) | 지시문 `structure-v2`, 추론 모드 |
| 답 검사: 나쁜 답 잡기 | 122/148 (82.4%) | `check-v2`. 규칙으로 만든 나쁜 답 |
| 답 검사: 좋은 답 통과 | 134/148 (90.5%) | `check-v2` |
| 주장 뽑기: 수치 | 132/281 (47.0%) | 공개 데이터, `structure-v2`. 느슨한 기준이면 244/281 |
| 주장 뽑기: 대상 | 94/273 (34.4%) | 같은 측정. 느슨한 기준이면 192/273 |
| 주장 뽑기: 한정 조건 | 31/79 (39.2%) | 같은 측정. 느슨한 기준이면 59/79 |
| 질문 해석: 주제와 조건 둘 다 | 14/50 | `interpret-v1`. 이름이 포함되면 맞다고 치면 40/50 |
| 관측/결정: 결정 / 관측 | 37/50, 45/50 | 관측을 결정으로 잘못 본 경우 4/50 |
| QA20 전체 흐름 | 자동 문자열 대조 10/20 | 문서 10/17, 채팅 0/3. 공식 점수는 사람 판정 후 |

지시문은 이후 `structure-v3`, `interpret-v2`로 바뀌었습니다. 위 표에서 QA20만 이 지시문으로 돌렸고, 인용과 세 모듈은 다시 재지 않았습니다.
QA20은 20문항 중 16문항에 인용이 달렸고, 원문 위치와 글자가 맞지 않는 인용은 0건이었습니다.

## 알려진 문제

- **주제 찾기:** QA20에서 틀린 10문항 중 6문항은 질문을 알맞은 주제에 연결하지 못한 경우입니다. 3문항은 추출 누락, 1문항은 호출 실패입니다.
- **조건 남발:** Git 문서 주장의 약 74%(328/441)에 조건이 붙었습니다. 그래서 일부 충돌이 `conflict`가 아니라 `by_condition`으로 나왔습니다.
- **`safe_answer` 언어:** 영어 질문에도 한국어 문구가 나옵니다.

## 설계 문서와 다른 점

- `docs/design_v2.md`의 D14 ⑥과 D15에는 1층 기준 숫자(90%, 95%)가 남아 있습니다. 실제로는 기준 없이 개수만 보고하기로 했고, 문서에는 아직 반영하지 않았습니다.
- 공개 데이터로 측정하기로 한 결정도 문서에 아직 없습니다.

## 데이터 취급

- 측정 원본과 변환 결과, QA20 패키지와 채점 키, 호출 기록, 결과 파일은 이 저장소에 없습니다. 재배포 조건 때문에 앞으로도 올리지 않습니다.
- `.gitignore`가 `results/`, `data/`, `datasets/`, `.env`, `.cache/`를 막습니다.
