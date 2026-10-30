# 3편. 하네스 코드 해설 (`harness/` 폴더)

`harness/` 폴더는 우리 시스템 본체다. 1편의 비유로 말하면 **꼼꼼한 총무**다.

이 편에서는 파일을 하나씩 열어서 코드가 **한 줄 한 줄** 무슨 뜻인지 설명한다. 코드는 실제 파일에서 가져왔다. 다만 읽기 쉽게 타입 표시를 빼거나, 주석을 덧붙이거나, 긴 부분을 `...`로 줄인 곳이 있다. 정확한 원본은 각 파일을 열어 확인하면 된다.

## 0. 파이썬 읽는 법 (최소한만)

코드를 처음 본다면 아래만 알면 된다.

| 코드 | 뜻 |
|---|---|
| `# 글` | **주석.** 컴퓨터는 무시하고 사람만 읽는 메모 |
| `"""글"""` | **설명문(docstring).** 파일·함수가 무엇을 하는지 적는 긴 메모 |
| `import X`, `from X import Y` | 다른 파일이나 도구 상자에서 기능을 빌려온다 |
| `x = 3` | `x`라는 이름의 상자에 3을 넣는다 (변수) |
| `def 이름(재료):` | **함수.** "재료를 받아 어떤 일을 하는 동작"을 정의한다 |
| `return 값` | 함수가 일을 마치고 돌려주는 결과 |
| `class 이름:` | **클래스.** 설계도. 이 설계도로 만든 물건을 "객체"라고 한다 |
| `self` | 클래스 안에서 "나 자신(이 객체)"을 가리키는 말 |
| `@dataclass` | "칸만 정의하면 나머지는 알아서 만들어줘"라는 표시. 데이터를 담는 클래스에 쓴다 |
| `if 조건:` / `else:` | 조건이 맞으면 / 아니면 |
| `for x in 목록:` | 목록에서 하나씩 꺼내 반복한다 |
| `[1, 2, 3]` | **리스트(목록)** |
| `{"키": 값}` | **딕셔너리(사전).** 이름표로 값을 찾는다 |
| `(a, b)` | **튜플.** 고칠 수 없는 묶음 |
| `[r for r in rs if 조건]` | rs에서 조건 맞는 것만 골라 새 목록을 만든다 (리스트 컴프리헨션) |
| `f"안녕 {name}"` | 글 안에 변수 값을 끼워 넣는다 (f-string) |
| `x: int` | "x에는 정수가 들어간다"는 **타입 표시.** 실행에는 영향 없고 읽기 쉽게 하는 용도 |
| `str`, `int`, `bool`, `None` | 글자, 정수, 참/거짓, "없음" |
| `from __future__ import annotations` | 타입 표시를 나중에 해석하라는 기술적 설정. 신경 쓰지 않아도 된다 |

## 파일 지도와 읽는 순서

```
harness/
├── schema.py      ① 데이터 모양 (모든 파일이 이걸 씀)
├── conditions.py  ② 조건 비교 규칙
├── verifier.py    ③ 인용 검증
├── pii.py         ④ 민감 정보 차단
├── relation.py    ⑤ 관계 판정
├── store.py       ⑥ 저장소 (③④⑤를 차례로 부름)
├── retriever.py   ⑦ 검색
├── answer.py      ⑧ 답변 구성 (②를 씀)
├── context.py     ⑨ AI에게 넘길 글 만들기
├── llm.py         ⑩ AI 연결
├── pipeline.py    ⑪ 전부 연결 (Harness 클래스)
└── __init__.py    ⑫ 바깥에 보여줄 이름 목록
```

---

## ① `schema.py`: 데이터의 모양

모든 파일이 주고받는 **데이터 모양**을 정한다. 설문지 양식을 먼저 정해두는 것과 같다.

```python
CANDIDATE = "candidate"  # 개인/AI가 올린 공유 후보
APPROVED = "approved"    # 팀 합의를 거쳐 승격된 팀 주장
```
- 기록의 상태 두 가지에 이름을 붙였다. 글자를 직접 쓰면 오타가 나기 쉬워서 이름으로 부른다.

```python
ANSWERED = "answered"                # 조건에 맞는 승인 근거로 답할 수 있음
CONFLICT = "conflict"                # 같은 조건에서 서로 다른 주장이 공존
ONLY_UNAPPROVED = "only_unapproved"  # 근거가 미승인 후보뿐
NO_EVIDENCE = "no_evidence"          # 질문 조건에 맞는 근거 없음
STATUSES = (ANSWERED, CONFLICT, ONLY_UNAPPROVED, NO_EVIDENCE)
```
- 답변 상태 네 가지다. 하네스의 핵심 아이디어인 **"확실한 것과 아닌 것을 구분해서 답하기"**가 이 네 가지 상태로 표현된다.
- `STATUSES`는 네 가지를 한데 묶은 것이다. 나중에 AI가 엉뚱한 상태를 말하는지 검사할 때 쓴다.

```python
@dataclass(frozen=True)
class Evidence:
    source: str  # 원문 문서 id (예: exp_001)
    rev: int     # 원문 버전
    quote: str   # 인용 구간
```
- **근거 하나**의 모양: 어느 문서, 몇 번째 판, 어떤 문장.
- `frozen=True`는 "한번 만들면 고칠 수 없음"이라는 뜻이다. 근거가 중간에 몰래 바뀌면 안 되기 때문이다.

```python
    @property
    def key(self) -> tuple[str, int, str]:
        """같은 원문·버전·구간이면 같은 근거로 본다."""
        return (self.source, self.rev, " ".join(self.quote.split()))
```
- 근거의 **지문**을 만든다. (문서, 판, 문장)이 같으면 같은 근거다.
- `" ".join(self.quote.split())`은 띄어쓰기가 두 칸이든 한 칸이든 똑같이 취급하려고 공백을 정리하는 코드다.
- **재인용 찾기**(R02, R10, R11)는 이 지문을 비교해서 한다.

```python
@dataclass
class Record:
    id: str
    created_at: str
    author: str
    author_type: str  # human | ai
    text: str
    topic: str
    value: str
    conditions: dict[str, Any]
    evidence: list[Evidence]
    status: str = CANDIDATE
```
- **기록 하나**의 모양이다. 2편에서 본 records.json의 칸과 같다.
- `status: str = CANDIDATE`: 상태를 따로 안 적으면 기본값이 "후보"다. 아무 글이나 저절로 팀 사실이 되면 안 되기 때문이다.

```python
    # 하네스가 채우는 필드
    citation_valid: bool | None = None
    relations: list[tuple[str, str]] = field(default_factory=list)  # (상대 기록 id, 관계)
    needs_review: bool = False
    pii_types: list[str] = field(default_factory=list)  # 가린 민감 정보 종류
```
- 이 네 칸은 기록이 저장소에 들어올 때 **하네스가 채운다.**
  - `citation_valid`: 인용이 원문과 맞았나 (처음엔 `None` = 아직 모름)
  - `relations`: 다른 기록과의 관계 목록. 예: `("R01", "recitation")`
  - `needs_review`: 충돌이 있어서 팀 검토가 필요한가
  - `pii_types`: 가린 민감 정보 종류. 예: `["email", "phone"]`
- `field(default_factory=list)`는 "기록마다 새 빈 목록을 하나씩 만들어 줘"라는 뜻이다. 모든 기록이 같은 목록을 나눠 쓰는 사고를 막는다.

```python
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Record":
        return cls(
            id=d["id"],
            ...
            value=str(d["value"]),
            conditions=dict(d.get("conditions", {})),
            evidence=[Evidence(**e) for e in d.get("evidence", [])],
            status=d.get("status", CANDIDATE),
        )
```
- JSON 파일에서 읽은 사전(`d`)을 `Record` 객체로 바꾼다.
- **여기서 `_gold_...` 칸은 읽지 않는다.** 그래서 채점용 정답이 시스템에 새지 않는다.
- `d.get("conditions", {})`는 "conditions 칸이 있으면 쓰고, 없으면 빈 사전"이라는 뜻이다.
- `Evidence(**e)`는 사전 `{"source":..., "rev":..., "quote":...}`를 그대로 `Evidence`로 만든다.

```python
@dataclass
class Query:
    id: str
    question: str
    topic: str | None = None
    conditions: dict[str, Any] = field(default_factory=dict)
```
- **질문 하나**의 모양이다. `topic`과 `conditions`는 없을 수도 있다(`None`, 빈 사전).
- llm 모드에서는 질문 문장만 주고, 하네스가 직접 주제와 조건을 알아내야 한다.

```python
@dataclass
class Response:
    status: str
    supporting_ids: list[str]   # 답의 근거로 제시한 기록
    team_fact_ids: list[str]    # 그중 '팀이 합의한 사실'로 제시한 기록
    independent_evidence: int   # 답변이 주장하는 독립 근거 수
    answer: str = ""
    notes: list[str] = field(default_factory=list)
    exposed: list[str] = field(default_factory=list)
```
- **답안지 양식**이다. 하네스든 비교 대상이든 모두 이 양식으로 답한다. 그래야 같은 기준으로 채점할 수 있다.
  - `status`: 네 가지 상태 중 하나
  - `supporting_ids`: 근거로 쓴 기록 번호
  - `team_fact_ids`: 그중 "팀이 합의한 사실"이라고 말한 기록 (여기에 후보가 들어가면 **잘못된 합의**로 감점)
  - `independent_evidence`: 독립 근거 수 (재인용을 따로 세면 감점)
  - `answer`: 실제 답변 문장
  - `notes`: 안내문 (예: "R08은 인용이 틀려서 제외")
  - `exposed`: AI에게 넘어간 글 전체 (민감 정보 노출과 글 양을 잴 때 쓴다)

---

## ② `conditions.py`: 조건 비교 규칙

"이 기록이 이 질문 조건에 맞나?"를 판단한다. 파일 전체가 짧아서 전부 본다.

```python
def mismatched_keys(query_cond, record_cond):
    return [k for k, v in query_cond.items() if k in record_cond and record_cond[k] != v]
```
- 질문 조건을 하나씩 본다(`k`=조건 이름, `v`=질문의 값).
- **기록에도 그 조건이 있는데 값이 다르면** "안 맞는 조건" 목록에 넣는다.
- 예: 질문 {피처: 40, 데이터: v1}, 기록 {피처: 12, 데이터: v1} → `["n_features"]`

```python
def is_compatible(query_cond, record_cond):
    return not mismatched_keys(query_cond, record_cond)
```
- 안 맞는 조건이 하나도 없으면 `True`(맞음)다.
- **규칙:** 기록에 아예 없는 조건은 "제한 없음"으로 본다. R12(결측치, 피처 수 없음)는 피처 수가 몇 개든 쓸 수 있다는 뜻이다. 팀이 정한 A안이 이것이다.

```python
def same_conditions(a, b):
    return a == b
```
- 두 조건이 **완전히 같은지** 본다. 관계 판정에서 "같은 조건인가?"를 물을 때 쓴다.

```python
def describe(cond):
    return ", ".join(f"{k}={v}" for k, v in sorted(cond.items())) or "조건 없음"
```
- 조건을 사람이 읽을 글로 바꾼다. `{"n_features": 12, "dataset": "v1"}` → `"dataset=v1, n_features=12"`
- 조건이 비어 있으면 "조건 없음"이라고 쓴다.

---

## ③ `verifier.py`: 인용 검증

**"원문에 정말 그렇게 써 있어?"**를 확인한다. R08처럼 AI가 숫자를 잘못 옮긴 인용을 잡는다.

```python
FUZZY_ACCEPT = 0.92
FUZZY_AMBIGUOUS = 0.75
_NUM = re.compile(r"\d+(?:\.\d+)?")
```
- `FUZZY_ACCEPT`: 원문과 92% 이상 비슷하면 "맞는 인용"으로 인정한다. 띄어쓰기나 조사 차이 정도는 봐준다.
- `FUZZY_AMBIGUOUS`: 75~92% 사이면 애매하다. AI 판정이 연결돼 있으면 AI에게 묻는다.
- `_NUM`: 글 속의 숫자(0.05, 12 같은 것)를 찾는 정규식이다.

```python
class SourceStore:
    def __init__(self, root):
        self.root = Path(root)
        self._cache = {}

    def get(self, source, rev):
        key = (source, rev)
        if key not in self._cache:
            path = self.root / f"{source}.md"
            self._cache[key] = path.read_text(encoding="utf-8") if path.exists() else None
        return self._cache[key]
```
- **원문 서랍**이다. `get("exp_001", 1)`이라고 하면 `data/sources/exp_001.md`를 읽어서 준다.
- 한 번 읽은 문서는 `_cache`에 넣어두고 다음엔 파일을 다시 열지 않는다.
- 파일이 없으면 `None`을 돌려준다. 그러면 검증에서 "틀린 인용"이 된다.
- 지금은 판(rev)이 1뿐이다. 버전 관리는 나중 과제다.

```python
class CitationVerifier:
    def __init__(self, sources, llm_judge=None):
        self.sources = sources
        self.llm_judge = llm_judge
        self._cache = {}
        self.stats = {"calls": 0, "cache_hits": 0, "llm_calls": 0}
```
- 검증기를 만든다. 원문 서랍과 선택 사항인 AI 판정기를 받는다.
- `stats`는 몇 번 검증했고 캐시를 몇 번 썼는지 세는 계산기다. 실험 출력의 "인용 검증 캐시: {...}"가 이것이다.

```python
    def verify(self, ev):
        self.stats["calls"] += 1
        if ev.key in self._cache:
            self.stats["cache_hits"] += 1
            return self._cache[ev.key]
        result = self._verify_uncached(ev)
        self._cache[ev.key] = result
        return result
```
- 근거 하나를 검증한다.
- **이미 검증한 지문(`ev.key`)이면 다시 검사하지 않는다.** 재인용(R02, R10, R11)은 원래 기록과 지문이 같아서 바로 답이 나온다.
- 출력에 `cache_hits: 3`이 나오는 이유가 이 재인용 3건이다. **효율성 설계**의 한 예다.

```python
    def _verify_uncached(self, ev):
        text = self.sources.get(ev.source, ev.rev)
        if text is None:
            return False
```
- 원문을 꺼낸다. 원문이 없으면 틀린 인용이다.

```python
        quote, body = _norm(ev.quote), _norm(text)
        if quote in body:
            return True
```
- 인용과 원문의 공백을 정리한 뒤, **인용이 원문에 글자 그대로 들어 있으면** 바로 통과다. 대부분의 정상 인용이 여기서 끝난다.

```python
        best, window = _best_window(quote, body)
        if _NUM.findall(quote) != _NUM.findall(window):
            return False
```
- 글자 그대로는 없으면, 원문에서 **가장 비슷한 구간**을 찾는다.
- 그 구간과 인용의 **숫자가 다르면 무조건 틀린 인용**이다.
- 예: R08 "learning_rate **0.1**에서 최고 성능" vs 원문 "learning_rate **0.05**에서 최고 성능". 글자는 거의 같아서 비슷한 정도(유사도)가 높게 나온다. 하지만 숫자가 다르니 잡아낸다. 이 규칙이 없으면 R08이 통과돼 버린다.

```python
        if best >= FUZZY_ACCEPT:
            return True
        if best >= FUZZY_AMBIGUOUS and self.llm_judge is not None:
            self.stats["llm_calls"] += 1
            return self.llm_judge(text, ev.quote)
        return False
```
- 숫자가 같고 92% 이상 비슷하면 통과다.
- 75~92%면 AI에게 묻는다. **비싼 AI는 애매할 때만 부른다**는 효율성 설계다. 지금 실험에서는 이 경우가 0번이었다.
- 그 외에는 틀린 인용이다.

```python
def _best_window(quote, body):
    n = len(quote)
    if n == 0 or not body:
        return 0.0, ""
    best, best_window = 0.0, ""
    for i in range(0, max(1, len(body) - n + 1)):
        window = body[i:i + n]
        ratio = SequenceMatcher(None, quote, window).ratio()
        if ratio > best:
            best, best_window = ratio, window
    return best, best_window
```
- 원문 위에 인용 길이만한 **창문**을 올려놓고 한 글자씩 밀면서 가장 비슷한 곳을 찾는다.
- `SequenceMatcher(...).ratio()`는 두 글이 얼마나 비슷한지 0~1 사이 숫자로 알려주는 파이썬 기본 도구다.

---

## ④ `pii.py`: 민감 정보 차단

전화번호, 이메일, 주민번호, API 키, 실명을 `[... 가림]`으로 바꾼다.

```python
PATTERNS = {
    "rrn": re.compile(r"\b\d{6}-[1-4]\d{6}\b"),                      # 주민등록번호
    "phone": re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"),           # 휴대전화
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "api_key": re.compile(r"\b(?:sk|pk|api|key)[-_](?:live[-_]|test[-_])?[A-Za-z0-9]{16,}\b"),
}
```
- 민감 정보의 **글자 모양**을 정규식으로 적었다.
  - 주민번호: 숫자 6개 - (1~4로 시작하는) 숫자 7개
  - 휴대전화: 010 같은 앞자리 - 숫자 3~4개 - 숫자 4개 (`-?`는 "하이픈이 있어도 되고 없어도 됨")
  - 이메일: 글자 @ 글자 . 글자
  - API 키: sk- 또는 pk- 같은 접두어 뒤에 영문·숫자 16개 이상
- `\b`는 "단어의 경계"라는 뜻이다. 다른 숫자 중간에 걸리는 것을 막는다.

```python
class PIIGuard:
    def __init__(self, llm_detector=None):
        self.llm_detector = llm_detector
        self.stats = {"checked": 0, "masked_records": 0, "masked_spans": 0}
```
- 민감 정보 차단기다. `llm_detector`는 실명처럼 모양이 없는 정보를 찾는 AI 함수다(선택).
- rule 모드에서는 비어 있고, llm 모드에서는 작은 AI 모델이 연결된다.

```python
    def mask(self, text, deep=True):
        self.stats["checked"] += 1
        kinds = []
        for kind, pat in PATTERNS.items():
            for span in set(m.group() for m in pat.finditer(text)):
                text = text.replace(span, f"[{kind.upper()} 가림]")
                kinds.append(kind)
```
- 정규식 네 개를 차례로 적용해서 찾은 부분을 `[PHONE 가림]` 같은 글로 바꾼다.
- 찾은 종류는 `kinds`에 적는다. 나중에 "R14: 민감 정보(email, phone)를 가리고 공유"라는 안내문이 된다.

```python
        if deep and self.llm_detector is not None:
            for span in self.llm_detector(text):
                if span and span in text:
                    text = text.replace(span, "[NAME 가림]")
                    kinds.append("name")
        self.stats["masked_spans"] += len(kinds)
        return text, kinds
```
- 정규식으로 **먼저 가린 다음에** AI에게 "여기 사람 이름 있어?"라고 묻는다.
- 순서가 중요하다. 전화번호·이메일·키는 이미 가렸으니 **AI에게도 보내지 않는다.**
- `deep=False`면 AI를 부르지 않는다. 짧은 값이나 인용 조각처럼 본문에서 이미 검사한 부분에 쓴다. AI 호출 수를 줄이는 효율성 설계다.
- **한계:** 실명 자체는 판정용 AI에 전달된다. 실제 서비스라면 컴퓨터 안에서 도는 작은 모델(로컬 NER)을 써야 한다.

---

## ⑤ `relation.py`: 기록 사이 관계 판정

새 기록이 들어오면 기존 기록 하나하나와 **어떤 관계인지** 정한다. 발표 슬라이드의 관계 표가 이 파일이다.

```python
NONE = "none"                       # 관련 없음
CONDITION_DIFFERS = "condition_differs"  # 같은 주제, 조건 다름
RECITATION = "recitation"           # 같은 원문 구간 재인용
SUPPORT = "support"                 # 같은 조건, 같은 주장, 다른 근거 (독립 근거 +1)
CONFLICT = "conflict"               # 같은 조건, 다른 주장
_PRIORITY = [RECITATION, CONFLICT, SUPPORT, CONDITION_DIFFERS, NONE]
```
- 관계 다섯 가지와 **우선순위**다. 한 기록이 여러 기록과 여러 관계를 가질 때 대표 관계를 고르는 순서다.

```python
def judge_pair(new, old):
    if new.topic != old.topic:
        return NONE
    if {e.key for e in new.evidence} & {e.key for e in old.evidence}:
        return RECITATION
    if not same_conditions(new.conditions, old.conditions):
        return CONDITION_DIFFERS
    if new.value == old.value:
        return SUPPORT
    return CONFLICT
```
기록 두 개를 비교해서 관계를 정한다. **위에서부터 차례로** 따진다.
1. 주제가 다르면 → 관계 없음
2. 근거 지문이 하나라도 겹치면 → **재인용** (`&`는 두 묶음의 공통 부분)
3. 조건이 다르면 → **조건 다름** (R01과 R03: 같은 주제인데 v1 대 v2)
4. 조건도 같고 주장도 같으면 → **지지** (다른 실험이 같은 결론을 낸 것)
5. 조건은 같은데 주장이 다르면 → **충돌** (R01 XGBoost 대 R04 LightGBM)

```python
def judge(new, existing):
    links = [(old.id, rel) for old in existing if (rel := judge_pair(new, old)) != NONE]
    if not links:
        return NONE, []
    rels = {rel for _, rel in links}
    primary = next(r for r in _PRIORITY if r in rels)
    return primary, links
```
- 새 기록을 기존 기록 **전부와** 비교해서 관계가 있는 것만 모은다.
- `:=`는 "계산하면서 이름 붙이기"다. `judge_pair` 결과를 `rel`에 담으면서 동시에 비교한다.
- 우선순위 목록에서 가장 먼저 나오는 관계를 대표 관계로 고른다.
- 돌려주는 값은 (대표 관계, 전체 연결 목록) 두 가지다.

---

## ⑥ `store.py`: 팀 기록 저장소

기록이 들어올 때의 **검문 순서**를 정한다: 인용 검증 → PII 차단 → (구조화) → 관계 판정 → 저장.

```python
class RecordStore:
    def __init__(self, verifier, judge_relations=True, pii_guard=None, structurer=None):
        self.verifier = verifier
        self.pii_guard = pii_guard
        self.structurer = structurer
        self.judge_relations = judge_relations
        self.records = {}
        self.version = 0
        self.log = []
```
- 저장소에 필요한 부품을 받는다: 인용 검증기, PII 차단기, 구조화기(llm 모드일 때만).
- `records`: 기록 번호 → 기록을 담는 사전
- `version`: 기록이 하나 들어올 때마다 1씩 오른다. 답변 캐시를 언제 버릴지 정하는 데 쓴다(⑪에서 설명).
- `log`: (기록 번호, 대표 관계) 목록. 테스트에서 "R02는 재인용으로 판정됐나?"를 확인할 때 쓴다.

```python
    def add(self, rec):
        rec.citation_valid = all(self.verifier.verify(e) for e in rec.evidence) if rec.evidence else False
```
- **① 인용 검증.** 근거가 모두 맞으면 `True`다. 근거가 하나도 없으면 `False`다(근거 없는 주장은 인정하지 않는다).
- **원문 그대로의 상태에서** 검증한다. 가린 뒤에 검증하면 원문과 글자가 달라지기 때문이다.

```python
        if self.pii_guard is not None:
            self._mask(rec)
        if self.structurer is not None:
            self.structurer(rec)
```
- **② PII 차단.** 그다음 **③ 구조화**를 한다.
- 순서가 중요하다. 가린 사본으로 구조화하므로 구조화하는 외부 AI에게 민감 정보가 가지 않는다.

```python
        primary = relation.NONE
        if self.judge_relations:
            primary, links = relation.judge(rec, list(self.records.values()))
            rec.relations = links
            for other_id, rel in links:
                self.records[other_id].relations.append((rec.id, rel))
                if rel == relation.CONFLICT:
                    rec.needs_review = True
                    self.records[other_id].needs_review = True
```
- **④ 관계 판정.** 새 기록과 기존 기록 전부의 관계를 정하고, 양쪽 기록에 모두 적어둔다.
- **충돌이면 양쪽 모두 "검토 필요"로 표시한다.** 한쪽을 지우지 않고 둘 다 남긴다. Graphiti가 옛 사실을 무효 처리하는 방식과 다른 점이다.

```python
        self.records[rec.id] = rec
        self.version += 1
        self.log.append((rec.id, primary))
        return primary
```
- **⑤ 저장.** 버전을 올리고 기록을 남긴다.

```python
    def _mask(self, rec):
        kinds = []
        rec.text, k = self.pii_guard.mask(rec.text); kinds += k
        rec.value, k = self.pii_guard.mask(rec.value, deep=False); kinds += k
        masked = []
        for e in rec.evidence:
            quote, k = self.pii_guard.mask(e.quote, deep=False); kinds += k
            masked.append(Evidence(e.source, e.rev, quote))
        rec.evidence = masked
        rec.pii_types = sorted(set(kinds))
        if kinds:
            self.pii_guard.stats["masked_records"] += 1
```
- 기록의 본문, 값, 인용을 모두 검사해서 가린다.
- 본문만 AI 판정까지 하고(`deep` 기본값), 값과 인용은 정규식만 쓴다(`deep=False`).
- `Evidence`는 고칠 수 없는(frozen) 객체라서, 가린 인용으로 **새 근거를 만들어** 바꿔 끼운다.
- `sorted(set(kinds))`는 중복을 없애고 정렬한다.

```python
    def by_topic(self, topic):
        return [r for r in self.records.values() if r.topic == topic]

    def all(self):
        return list(self.records.values())
```
- 주제별 기록, 전체 기록을 꺼내는 편의 함수다.

---

## ⑦ `retriever.py`: 관련 기록 찾기

질문과 관련된 기록을 찾는다. 주제를 알면 주제로 찾고, 모르면 **BM25**(단어 겹침 점수)로 찾는다.

```python
def tokenize(text):
    words = re.findall(r"[0-9A-Za-z_.]+|[가-힣]+", text.lower())
    tokens = []
    for w in words:
        tokens.append(w)
        if re.match(r"[가-힣]", w) and len(w) > 2:
            tokens.extend(w[i:i + 2] for i in range(len(w) - 1))
    return tokens
```
- 글을 **낱말 조각**으로 자른다. 영어·숫자 덩어리와 한글 덩어리를 찾는다.
- 한글은 "결측치는"과 "결측치"가 다른 낱말로 취급되는 문제가 있다. 그래서 **두 글자씩** 잘라 추가한다. 예: "결측치는" → 결측, 측치, 치는
- 이렇게 하면 조사가 붙어도 겹치는 조각이 생겨서 검색이 된다.

```python
def record_text(r):
    cond = " ".join(f"{k} {v}" for k, v in r.conditions.items())
    return f"{r.text} {r.topic.replace('_', ' ')} {r.value} {cond}"
```
- 검색할 때 기록의 본문, 주제, 값, 조건을 한 줄로 이어 붙여서 쓴다.

```python
class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.toks = [tokenize(d) for d in docs]
        self.avgdl = sum(map(len, self.toks)) / max(1, len(self.toks))
        df = Counter(t for doc in self.toks for t in set(doc))
        n = len(self.toks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
```
- BM25 점수 계산기를 준비한다. 외부 도구 없이 직접 만들었다.
  - `toks`: 문서마다 자른 낱말 목록
  - `avgdl`: 문서 평균 길이
  - `df`: 각 낱말이 몇 개 문서에 나오나
  - `idf`: **흔한 낱말일수록 점수를 낮게** 준다. "이탈"처럼 모든 기록에 나오는 낱말은 구분에 도움이 안 되기 때문이다.
- `k1`, `b`: BM25의 표준 설정값이다. 같은 낱말이 여러 번 나올 때 점수를 얼마나 더 줄지, 긴 문서를 얼마나 깎을지 정한다.

```python
    def scores(self, query):
        q = tokenize(query)
        out = []
        for doc in self.toks:
            tf = Counter(doc)
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(doc) / self.avgdl))
            out.append(s)
        return out
```
- 질문의 낱말이 각 문서에 몇 번 나오는지(`tf`) 보고 점수를 더한다. 이게 BM25 공식이다.

```python
def bm25_top_k(records, question, k):
    if not records:
        return []
    scores = BM25([record_text(r) for r in records]).scores(question)
    ranked = sorted(zip(scores, records), key=lambda x: -x[0])
    return [r for s, r in ranked[:k] if s > 0]
```
- 점수가 높은 순으로 정렬해서 상위 `k`개를 돌려준다. 점수 0(겹치는 낱말 없음)은 뺀다.
- **일반 검색 베이스라인도 이 함수를 쓴다.** 같은 검색 도구를 쓰니 비교가 공정하다.

```python
class Retriever:
    def __init__(self, k=10):
        self.k = k

    def retrieve(self, records, q):
        if q.topic:
            return [r for r in records if r.topic == q.topic]
        return bm25_top_k(records, q.question, self.k)
```
- 하네스의 검색기다. 질문 주제를 알면 **같은 주제의 기록을 전부** 가져온다. 조건이 다른 것까지 다 가져오고, 거르는 일은 ⑧에서 한다.
- 주제를 모르면 BM25로 상위 10개를 가져온다.

---

## ⑧ `answer.py`: 답변 구성 (가장 중요한 파일)

검색된 기록을 걸러서 **네 가지 상태 중 하나로 판정**한다. 하네스의 핵심 판단이 여기서 일어난다.

```python
MAX_NEARBY_NOTES = 3

@dataclass
class ComposerConfig:
    use_conditions: bool = True  # 조건 비교
    use_verifier: bool = True    # 인용 검증 결과 반영
    use_dedup: bool = True       # 재인용을 같은 근거로 묶기
    use_approval: bool = True    # 승인/후보 상태 구분
```
- `MAX_NEARBY_NOTES`: "조건이 다른 기록" 안내를 최대 몇 개까지 보여줄지 정한다(⑧-3에서 설명).
- `ComposerConfig`: **모듈 끄기 실험용 스위치**다. 기본은 전부 켜짐이다. 하나씩 꺼보면 각 기능이 얼마나 기여하는지 볼 수 있다.

### ⑧-1. 조건 필터

```python
def compose(q, candidates, cfg=ComposerConfig()):
    notes = []

    if cfg.use_conditions:
        compatible = [r for r in candidates if is_compatible(q.conditions, r.conditions)]
        nearby = [r for r in candidates if r not in compatible]
    else:
        compatible, nearby = list(candidates), []
```
- 검색된 후보를 **조건이 맞는 것(`compatible`)**과 **조건이 다른 것(`nearby`)**으로 나눈다.
- 스위치를 끄면 조건을 안 보고 전부 맞는 것으로 친다. 이렇게 하면 과잉 일반화가 늘어난다(실험에서 확인).

### ⑧-2. 인용 오류 제외

```python
    if cfg.use_verifier:
        bad = [r for r in compatible if not r.citation_valid]
        applicable = [r for r in compatible if r.citation_valid]
        for r in bad:
            notes.append(f"{r.id}: 인용이 원문과 맞지 않아 근거에서 제외")
    else:
        applicable = compatible
```
- 인용 검증에서 떨어진 기록(R08)을 빼고, 왜 뺐는지 안내문을 남긴다.
- 남은 `applicable`이 **진짜로 근거로 쓸 수 있는 기록**이다.

### ⑧-3. 근거가 없으면 → `no_evidence`

```python
    if not applicable:
        nearby = sorted(nearby, key=lambda r: len(mismatched_keys(q.conditions, r.conditions)))
        for r in nearby[:MAX_NEARBY_NOTES]:
            keys = mismatched_keys(q.conditions, r.conditions)
            notes.append(f"{r.id}({r.value})는 조건이 다름: " + ", ".join(
                f"{k} 질문={q.conditions[k]} / 기록={r.conditions[k]}" for k in keys))
        if len(nearby) > MAX_NEARBY_NOTES:
            notes.append(f"그 외 조건이 다른 기록 {len(nearby) - MAX_NEARBY_NOTES}건")
        return Response(status=NO_EVIDENCE, supporting_ids=[], team_fact_ids=[], independent_evidence=0,
            answer=f"[{describe(q.conditions)}] 조건에 맞는 팀 근거가 없습니다." + ...,
            notes=notes)
```
- 쓸 근거가 없으면 "근거 없음"으로 답한다. 이때 **조건이 가장 가까운 기록 3개**를 안내한다. 예: "R01(XGBoost)는 조건이 다름: n_features 질문=40 / 기록=12"
- 나머지는 "그 외 N건"으로 줄인다.
- **왜 3개만?** 처음에는 전부 나열했다. 그랬더니 기록 315개일 때 안내가 47줄이 되어 AI에게 넘길 글이 계속 길어졌다. 3개로 줄인 뒤에는 기록 수와 관계없이 일정해졌다(5편 참고).

### ⑧-4. 승인 여부와 독립 근거 수

```python
    approved = [r for r in applicable if r.status == APPROVED] if cfg.use_approval else applicable
    if cfg.use_dedup:
        independent = len({e.key for r in applicable for e in r.evidence})
    else:
        independent = sum(len(r.evidence) for r in applicable)
```
- `approved`: 근거 중 **팀이 승인한 것만** 고른다.
- `independent`: 근거 지문(`key`)의 **서로 다른 개수**를 센다. R09·R10·R11은 지문이 같아서 1개다.
- 재인용 묶기를 끄면 그냥 근거 개수를 더해서 3개가 된다(틀린 값).

### ⑧-5. 상태 판정

```python
    values = sorted({r.value for r in applicable})
    if len(values) > 1:
        status = CONFLICT
        ...
        text = f"같은 조건에서 주장이 엇갈립니다 → {sides}. 팀 검토가 필요합니다."
    elif cfg.use_approval and not approved:
        status = ONLY_UNAPPROVED
        text = f"'{values[0]}' 기록이 있지만 아직 팀 승인 전 후보입니다(작성: ...). 팀 사실로 보기 어렵습니다."
    else:
        status = ANSWERED
        text = f"{values[0]} (승인된 팀 근거 {len(approved)}건, 독립 근거 {independent}개)"
```
상태를 판정하는 순서는 이렇다.
1. 근거들의 주장이 **두 가지 이상**이면 → **충돌**. 양쪽 주장과 승인 여부, 작성자를 모두 보여준다.
2. 주장은 하나인데 **승인된 근거가 없으면** → **승인 전 후보뿐**
3. 그 외 → **답할 수 있음**

```python
    if cfg.use_dedup:
        dup = sum(len(r.evidence) for r in applicable) - independent
        if dup > 0:
            notes.append(f"재인용 {dup}건은 같은 근거로 묶음")

    for r in applicable:
        if r.pii_types:
            notes.append(f"{r.id}: 민감 정보({', '.join(r.pii_types)})를 가리고 공유")

    return Response(status=status, supporting_ids=[r.id for r in applicable],
                    team_fact_ids=[r.id for r in approved], independent_evidence=independent,
                    answer=f"[{describe(q.conditions)}] {text}", notes=notes,
                    exposed=[r.text for r in applicable])
```
- 재인용 몇 건을 묶었는지, 민감 정보를 가렸는지 안내문을 붙인다.
- 답안지(`Response`)를 채워서 돌려준다. **팀 사실(`team_fact_ids`)에는 승인된 기록만** 들어간다.

---

## ⑨ `context.py`: AI에게 넘길 글 만들기

공정 비교(llm 모드)에서 **AI 답변기에 무엇을 넘길지** 만든다.

```python
def _evidence(r):
    return "; ".join(f"{e.source} rev{e.rev} \"{e.quote}\"" for e in r.evidence)

def raw_line(r):
    return (f"[{r.id}] 작성자: {r.author}({r.author_type}) | 상태: {r.status} | 작성일: {r.created_at} "
            f"| 주장: {r.text} | 근거: {_evidence(r)}")
```
- 기록 원본을 한 줄로 만든다. 예: `[R01] 작성자: 정시찬(human) | 상태: approved | ... | 주장: 이탈 예측 모델은 XGBoost가 가장 좋다. | 근거: exp_001 rev1 "XGBoost AUC 0.842"`
- **조건 칸은 일부러 넣지 않는다.** 조건은 원문을 읽어서 알아내야 한다. 그래야 모든 시스템이 같은 조건에서 출발한다.

```python
def source_block(source, sources):
    text = sources.get(source, 1) or "(원문 없음)"
    return f"<source id=\"{source}\">\n{text.strip()}\n</source>"

def raw_context(records, sources):
    lines = [raw_line(r) for r in records]
    seen = []
    for r in records:
        for e in r.evidence:
            if e.source not in seen:
                seen.append(e.source)
    return lines + [source_block(s, sources) for s in seen]
```
- 기록 줄 뒤에 그 기록들이 인용한 **원문 문서 전체**를 붙인다. 같은 문서는 한 번만 붙인다.
- 베이스라인(일반 검색, 전체 맥락)은 이 함수를 쓴다. AI가 원문을 보고 조건과 인용을 직접 확인할 수 있게 하려는 것이다.

```python
def harness_context(resp, records):
    lines = [f"[하네스 판정] {resp.status}: {resp.answer}"]
    lines += [f"[하네스 안내] {n}" for n in resp.notes]
    for rid in resp.supporting_ids:
        r = records[rid]
        lines.append(f"[{r.id}] 작성자: ... | 상태: {r.status} | 조건: {describe(r.conditions)} "
                     f"| 주장: {r.text} | 근거(원문 대조 완료): {_evidence(r)}")
    return lines
```
- 하네스가 AI에게 넘기는 글이다.
  - 하네스의 판정 결과(예: "conflict: 같은 조건에서 주장이 엇갈립니다…")
  - 안내문
  - **조건이 맞고 검증된 기록만**. 민감 정보는 이미 가려져 있다.
- 원문 문서를 통째로 붙이지 않으니 글이 짧다. 이게 맥락 크기가 330자로 작은 이유다.

```python
def answer_with_llm(question, context, notes=None):
    from . import llm
    out = llm.answer(question, context)
    return Response(out.status, out.supporting_ids, out.team_fact_ids, out.independent_evidence,
                    answer=out.answer, notes=list(notes or []), exposed=list(context))
```
- **모든 시스템이 쓰는 공통 답변기**를 부른다. AI의 답을 답안지 양식으로 옮긴다.
- `exposed=list(context)`: AI에게 넘긴 글 전체를 기록해둔다. 채점할 때 민감 정보 노출과 글 양을 잰다.

---

## ⑩ `llm.py`: AI 연결

OpenAI(기본) 또는 Claude에 질문을 보내고, 정해진 모양(JSON)으로 답을 받는다. 같은 질문은 캐시에서 꺼낸다.

### 설정

```python
PROVIDER = os.environ.get("HARNESS_LLM_PROVIDER", "openai")
_DEFAULTS = {
    "openai": ("gpt-6-luna", "gpt-6-luna"),
    "anthropic": ("claude-haiku-5-5", "claude-opus-5-5"),
}
SMALL_MODEL = os.environ.get("HARNESS_SMALL_MODEL", _DEFAULTS[PROVIDER][0])
ANSWER_MODEL = os.environ.get("HARNESS_ANSWER_MODEL", _DEFAULTS[PROVIDER][1])
```
- `os.environ.get(이름, 기본값)`은 컴퓨터에 설정된 환경변수를 읽는다. 없으면 기본값을 쓴다.
- **어느 회사 AI를 쓸지**와 **작은 모델(앞단)·답변 모델**을 정한다.
- OpenAI는 Graphiti 기본값과 같은 모델을 쓴다. 그래야 비교가 공정하다.
- 효율성 설계상 앞단(구조화, PII 판정)은 작은 모델을 쓰도록 나눠 두었다. 지금은 둘 다 같은 모델로 실험했다.

### 캐시

```python
_CACHE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "llm_cache.json"
_cache = None
stats = {"calls": 0, "cache_hits": 0}
```
- AI 응답을 저장할 파일 위치(`.cache/llm_cache.json`)와 호출 횟수 계산기다.

```python
def _save_cache():
    _CACHE_PATH.parent.mkdir(exist_ok=True)
    if _CACHE_PATH.exists():
        try:
            on_disk = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            _cache.update({k: v for k, v in on_disk.items() if k not in _cache})
        except (json.JSONDecodeError, OSError):
            pass
    tmp = _CACHE_PATH.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(_cache, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _CACHE_PATH)
```
- 캐시를 파일에 저장한다.
- 터미널 두 개에서 동시에 실험을 돌릴 때 파일이 깨지지 않도록 두 가지를 한다.
  1. 저장하기 전에 다른 실행이 저장한 내용을 합친다.
  2. 임시 파일에 다 쓴 뒤 한 번에 바꿔치기한다.

```python
def _parse(model, prompt, schema):
    key = hashlib.sha256(f"{PROVIDER}|{model}|{schema.__name__}|{prompt}".encode()).hexdigest()
    cache = _load_cache()
    if key in cache:
        stats["cache_hits"] += 1
        return schema.model_validate(cache[key])
    stats["calls"] += 1
    out = _parse_openai(...) if PROVIDER == "openai" else _parse_anthropic(...)
    cache[key] = out.model_dump()
    _save_cache()
    return out
```
- **AI를 부르는 모든 길이 지나는 관문**이다.
- `sha256`: 질문 내용으로 **고유한 지문**을 만든다. 같은 회사·모델·양식·질문이면 지문이 같다.
- 지문이 캐시에 있으면 **AI를 부르지 않고** 저장된 답을 쓴다. 실험을 다시 돌릴 때 "캐시 재사용 969회"처럼 나오는 게 이것이고, 그만큼 돈이 들지 않는다.
- 없으면 AI를 부르고 답을 저장한다.

```python
def _parse_openai(model, prompt, schema):
    ...
    resp = _client.chat.completions.parse(
        model=model, response_format=schema, messages=[{"role": "user", "content": prompt}])
    msg = resp.choices[0].message
    if msg.parsed is None:
        raise RuntimeError(f"모델이 구조화 응답을 주지 않았습니다: {msg.refusal}")
    return msg.parsed
```
- OpenAI에 질문을 보낸다. `response_format=schema`는 **"이 양식(JSON)으로만 답해"**라고 강제하는 기능이다. 그래서 AI 답을 프로그램이 바로 읽을 수 있다.
- AI가 답을 거절하면 오류를 낸다.
- `_parse_anthropic`은 Claude용으로 같은 일을 한다.

### 조건 규칙 (공통)

```python
def _conditions(n_features, dataset):
    cond = {}
    if n_features is not None:
        cond["n_features"] = n_features
    if dataset:
        cond["dataset"] = dataset.strip().lower()
    return cond
```
- AI가 뽑은 피처 수와 데이터 버전을 조건 사전으로 만든다. "V1 "처럼 대문자나 공백이 섞여도 "v1"로 맞춘다.
- **조건 이름을 두 개로 고정했다.** 팀이 아직 정하지 않은 열린 질문이라 초안이다.

### 기록 구조화

```python
class StructuredRecord(BaseModel):
    topic: str
    value: str
    n_features: int | None
    dataset: str | None

def structure_record(text, source_text, known):
    prompt = ("팀 실험 기록을 구조화하라.\n"
        "- topic: ... 기존 topic과 같은 종류면 반드시 그 이름을 그대로 쓴다.\n"
        "- value: ... 기존 value와 같은 뜻이면 그 표기를 그대로 쓴다.\n" ...
        f"<existing_topics>{...known...}</existing_topics>\n<record>{text}</record>\n<source>{source_text}</source>")
    out = _parse(SMALL_MODEL, prompt, StructuredRecord)
    return out.topic.strip(), out.value.strip(), _conditions(out.n_features, out.dataset)
```
- AI에게 "기록 문장과 원문을 보고 주제·값·조건을 뽑아"라고 시킨다.
- **이미 있는 주제 이름 목록(`known`)을 같이 준다.** 그래야 AI가 같은 주제를 "best_model", "model_choice"처럼 제각각 부르지 않는다. 같은 주제로 묶여야 관계 판정과 검색이 된다.

### 질문 파싱

```python
def parse_query(question, known_topics):
    ...
    out = _parse(SMALL_MODEL, prompt, ParsedQuery)
    topic = out.topic.strip()
    return (topic if topic in known_topics else None), _conditions(out.n_features, out.dataset)
```
- 질문에서 주제와 조건을 뽑는다. AI가 목록에 없는 주제를 지어내면 `None`으로 처리하고 BM25 검색으로 넘어간다.

### 공통 답변기

```python
class LLMAnswer(BaseModel):
    status: Literal["answered", "conflict", "only_unapproved", "no_evidence"]
    supporting_ids: list[str]
    team_fact_ids: list[str]
    independent_evidence: int
    answer: str

ANSWER_INSTRUCTIONS = """너는 팀 공유 기록을 근거로 팀원의 질문에 답하는 AI다. ...
- 질문의 조건과 맞는 기록만 근거로 쓴다. ...
- 원문과 맞지 않는 인용을 가진 기록은 근거로 쓰지 않는다.
- status는 다음 중 하나다. answered / conflict / only_unapproved / no_evidence ...
- independent_evidence: ... 같은 원문·버전·구간을 다시 인용한 기록은 1개로 센다 ..."""

def answer(question, context):
    prompt = ANSWER_INSTRUCTIONS + "\n<context>\n" + "\n".join(context) + "\n</context>\n" + f"<question>{question}</question>"
    return _parse(ANSWER_MODEL, prompt, LLMAnswer)
```
- **모든 시스템이 똑같이 쓰는 답변기**다. 답안지 양식(`LLMAnswer`)으로만 답하게 강제한다. `Literal`은 "이 네 개 중 하나만 허용"이라는 뜻이다.
- **판단 규칙을 프롬프트에 모두 적었다.** 베이스라인에게도 똑같이 준다. 공정성을 위해서다. 그 결과 기록이 적을 때는 베이스라인도 꽤 잘 맞혔다(5편).
- 시스템마다 다른 것은 `context`, 즉 **AI에게 넘기는 참고 자료**뿐이다.

### 실명 찾기

```python
def detect_pii_spans(text):
    prompt = ("아래 팀 기록에서 개인을 식별할 수 있는 정보(실명, 주소, 계정명 등)를 원문 그대로 뽑아라. "
              "모델명·수치·실험 조건·팀원 이름(작성자)은 제외한다. 없으면 빈 목록.\n\n" f"<record>{text}</record>")
    return _parse(SMALL_MODEL, prompt, PIISpans).spans
```
- ④ PII 차단기에 연결되는 함수다. 정규식이 못 잡는 실명(예: 김민수)을 찾는다.

---

## ⑪ `pipeline.py`: 전부 연결하기 (`Harness` 클래스)

지금까지 본 부품을 조립한 **완성품**이다. 실험할 때 만드는 것이 이 `Harness`다.

```python
class Harness:
    name = "harness"

    def __init__(self, sources_dir, cfg=None, llm_judge=None, use_cache=True, use_pii=True,
                 structure="gold", answerer="rule"):
        self.cfg = cfg or ComposerConfig()
        self.structure, self.answerer = structure, answerer
        self.sources = SourceStore(sources_dir)
        self.verifier = CitationVerifier(self.sources, llm_judge=llm_judge)
```
- 하네스를 만들 때 정하는 것들:
  - `cfg`: 모듈 끄기 스위치
  - `use_pii`: PII 차단을 켤지
  - `structure`: `"gold"`면 정답 구조를 그대로 쓰고, `"llm"`이면 AI로 직접 구조화한다
  - `answerer`: `"rule"`이면 템플릿으로 답하고, `"llm"`이면 공통 AI 답변기를 쓴다
- 원문 서랍과 인용 검증기를 만든다.

```python
        self.pii_guard = None
        if use_pii:
            detector = None
            if structure == "llm":
                from .llm import detect_pii_spans
                detector = detect_pii_spans
            self.pii_guard = PIIGuard(llm_detector=detector)
```
- PII 차단기를 만든다. llm 모드에서만 실명 판정 AI를 연결한다.

```python
        self.store = RecordStore(self.verifier, pii_guard=self.pii_guard,
                                 structurer=self._structure if structure == "llm" else None)
        self.retriever = Retriever()
        self.use_cache = use_cache
        self._answer_cache = {}
        self.stats = {"queries": 0, "answer_cache_hits": 0}
```
- 저장소, 검색기, 답변 캐시를 만든다.

```python
    def _structure(self, rec):
        from .llm import structure_record
        known = {}
        for r in self.store.all():
            values = known.setdefault(r.topic, [])
            if r.value not in values:
                values.append(r.value)
        source = "\n".join(self.sources.get(e.source, e.rev) or "" for e in rec.evidence)
        if self.pii_guard is not None:
            source, _ = self.pii_guard.mask(source)
        rec.topic, rec.value, rec.conditions = structure_record(rec.text, source, known)
```
- llm 모드에서 기록 하나를 구조화한다.
  1. 지금까지 저장된 주제와 값 목록(`known`)을 만든다.
  2. 기록이 인용한 원문을 가져와서 **민감 정보를 가린다.** exp_009에는 고객 전화번호가 있다.
  3. AI로 주제·값·조건을 뽑아 기록에 채운다.

```python
    def ingest(self, records):
        ordered = sorted(records, key=lambda r: r.created_at)
        for i, r in enumerate(ordered, 1):
            self.store.add(r)
            if self.structure == "llm" and (i % 25 == 0 or i == len(ordered)):
                print(f"  [{self.name}] 기록 구조화 {i}/{len(ordered)}", flush=True)
```
- 기록을 **올린 시간 순서대로** 넣는다. 관계 판정은 "먼저 있던 기록"과 비교하는 것이라 순서가 중요하다.
- llm 모드에서는 25개마다 진행 상황을 출력한다.

```python
    def ask(self, q):
        self.stats["queries"] += 1
        if self.structure == "llm":
            from .llm import parse_query
            topic, cond = parse_query(q.question, sorted({r.topic for r in self.store.all()}))
            q = Query(q.id, q.question, topic, cond)
```
- 질문을 받는다. llm 모드면 먼저 질문에서 주제와 조건을 뽑는다.

```python
        key = None
        if self.use_cache and q.topic:
            key = (q.topic, tuple(sorted(q.conditions.items())), self.store.version, q.question)
            if key in self._answer_cache:
                self.stats["answer_cache_hits"] += 1
                return self._answer_cache[key]
```
- **답변 캐시.** (주제, 조건, 저장소 버전, 질문)이 같으면 전에 만든 답을 그대로 쓴다.
- 저장소 버전이 들어 있어서, **새 기록이 들어오면 자동으로 새로 계산한다.** 테스트로 확인했다.

```python
        candidates = self.retriever.retrieve(self.store.all(), q)
        resp = compose(q, candidates, self.cfg)
        if self.answerer == "llm":
            resp = answer_with_llm(q.question, harness_context(resp, self.store.records), resp.notes)
        if key is not None:
            self._answer_cache[key] = resp
        return resp
```
- 하네스가 질문을 처리하는 순서는 이렇다.
  1. **검색** (⑦)
  2. **판정** (⑧)
  3. llm 모드면 판정 결과를 **공통 AI 답변기**에 넘긴다 (⑨, ⑩)
  4. 캐시에 저장하고 답을 돌려준다

---

## ⑫ `__init__.py`

```python
from .answer import ComposerConfig
from .pipeline import Harness
from .schema import Evidence, Query, Record, Response
__all__ = ["ComposerConfig", "Evidence", "Harness", "Query", "Record", "Response"]
```
- 바깥에서 `from harness import Harness`처럼 짧게 불러 쓸 수 있게 자주 쓰는 이름을 모아둔 파일이다.
