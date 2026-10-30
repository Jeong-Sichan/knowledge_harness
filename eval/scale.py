"""규모 실험용 방해 기록 생성기.

기존 15개 기록에 '주제와 문장은 비슷하지만 조건이 다른' 기록을 N개 섞는다.
방해 기록의 조건(피처 수 8~64, 데이터 v4~v7)은 어떤 정답 질문의 조건과도 겹치지 않는다.
그래서 정답 라벨은 그대로 유효하다. 바뀌는 것은 검색 난이도와 맥락 크기다.

    python -m eval.run_eval --scale 100 ...
"""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FEATURES = [8, 16, 20, 24, 30, 50, 64]
DATASETS = ["v4", "v5", "v6", "v7"]
AUTHORS = [("정시찬", "human"), ("박재원", "human"), ("정시찬의 AI", "ai"), ("박재원의 AI", "ai")]

# topic: (값 후보, 주장 문장, 원문 결과 문장 = 인용 구간, 조건에 피처 수 포함 여부, 제목)
TOPICS = {
    "best_model": (["XGBoost", "LightGBM", "CatBoost", "RandomForest"],
                   "이탈 예측 모델은 {v}가 가장 좋았다.", "{v} AUC 0.8{r}", True, "이탈 예측 모델 비교"),
    "imbalance_method": (["class_weight", "SMOTE", "언더샘플링"],
                         "클래스 불균형은 {v}로 처리하는 게 낫다.", "{v} 적용 시 F1이 0.0{r} 높았다", True, "클래스 불균형 처리 비교"),
    "xgb_learning_rate": (["0.01", "0.03", "0.05", "0.1"],
                          "XGBoost learning rate는 {v}가 최적이다.", "learning_rate {v}에서 최고 성능", True, "하이퍼파라미터 탐색"),
    "top_feature": (["tenure", "월 요금", "고객센터 문의 횟수", "약정 기간"],
                    "가장 중요한 피처는 {v}이다.", "{v}이(가) 가장 중요한 피처로 나타났다", True, "피처 중요도 분석"),
    "missing_value": (["median", "KNN", "평균"],
                      "결측치는 {v} 대체로 처리한다.", "{v} 대체를 채택했다", False, "결측치 처리 비교"),
    "threshold": (["0.3", "0.4", "0.5"],
                  "분류 임계값은 {v}가 적당하다.", "임계값 {v}에서 F1 최고", True, "임계값 조정"),
    "batch_size": (["256", "512", "1024"],
                   "학습 배치 크기는 {v}로 둔다.", "배치 크기 {v}가 가장 안정적이었다", True, "배치 크기 실험"),
}


def make_distractors(n: int, seed: int = 0) -> tuple[list[dict], dict[str, str]]:
    """(기록 목록, {source id: 원문}). 기록 형식은 data/records.json과 같다."""
    rng = random.Random(seed)
    records, sources = [], {}
    topics = list(TOPICS)
    for i in range(n):
        topic = topics[i % len(topics)]
        values, claim, result, with_features, title = TOPICS[topic]
        v = rng.choice(values)
        cond = {"dataset": rng.choice(DATASETS)}
        if with_features:
            cond["n_features"] = rng.choice(FEATURES)
        author, author_type = rng.choice(AUTHORS)
        sid = f"exp_d{i:04d}"
        quote = result.format(v=v, r=rng.randint(1, 9))
        cond_line = (f"피처 {cond['n_features']}개, " if "n_features" in cond else "") + f"데이터 {cond['dataset']}"
        sources[sid] = (f"# {sid} — {title} ({cond['dataset']})\n- 작성: {author} / 2026-10-{rng.randint(6, 28):02d}\n"
                        f"- 조건: {cond_line}\n\n## 결과\n{quote}.\n")
        records.append({
            "id": f"D{i:04d}", "created_at": f"2026-10-{rng.randint(6, 28):02d}T{rng.randint(9, 18):02d}:00",
            "author": author, "author_type": author_type, "text": claim.format(v=v),
            "topic": topic, "value": v, "conditions": cond,
            "evidence": [{"source": sid, "rev": 1, "quote": quote}],
            "status": rng.choice(["approved", "candidate"]),
        })
    return records, sources


def build_scaled_dataset(n: int, seed: int = 0) -> tuple[list[dict], Path]:
    """기존 기록 + 방해 기록 n개, 그리고 원문 폴더(기존 원문 + 방해 원문)를 만든다."""
    base = json.loads((ROOT / "data" / "records.json").read_text(encoding="utf-8"))
    extra, extra_sources = make_distractors(n, seed)
    out = ROOT / ".cache" / f"scale_{n}_seed{seed}" / "sources"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "data" / "sources", out)
    for sid, text in extra_sources.items():
        (out / f"{sid}.md").write_text(text, encoding="utf-8")
    return base + extra, out
