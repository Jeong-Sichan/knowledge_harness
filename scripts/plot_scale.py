"""규모 실험 그래프: 기록 수에 따른 질문당 맥락 크기 (docs/figures/context_vs_records.svg)

    python -m scripts.plot_scale

값은 docs/experiments.md 3차 실험(--answerer llm)의 context_chars다.
의존성 없이 SVG를 직접 쓴다(한글 글꼴 문제 없이 브라우저·슬라이드에서 그대로 보인다).
"""
from __future__ import annotations

import math
from pathlib import Path

RECORDS = [15, 115, 315]
# (이름, 표시 이름, 색, 마커, 값). 색은 기본 범주 팔레트 1~3번(검증 통과), 마커 모양으로 색 외 구분을 더한다.
SERIES = [
    ("harness", "하네스", "#2a78d6", "circle", [317, 330, 330]),
    ("full_context_llm", "전체 맥락 LLM", "#eb6834", "square", [4078, 31801, 87026]),
    ("retrieval_only", "BM25 검색", "#1baf7a", "triangle", [1558, 1575, 1611]),
]
NOTE = "하네스 15개 값은 안내문 상한 수정 전 측정치(수정 영향 미미). 질문 14개 평균."

W, H = 960, 540
L, R, T, B = 96, 210, 118, 96          # 플롯 여백 (오른쪽은 직접 레이블 자리)
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
FONT = "Pretendard, 'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif"
Y_MIN, Y_MAX = 100, 200_000


def x_of(n: int) -> float:
    lo, hi = RECORDS[0], RECORDS[-1]
    return L + (n - lo) / (hi - lo) * (W - L - R)


def y_of(v: float) -> float:
    a, b = math.log10(Y_MIN), math.log10(Y_MAX)
    return T + (1 - (math.log10(v) - a) / (b - a)) * (H - T - B)


def marker(kind: str, x: float, y: float, color: str) -> str:
    ring = f'stroke="{SURFACE}" stroke-width="2"'
    if kind == "circle":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}" {ring}/>'
    if kind == "square":
        return f'<rect x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" rx="2" fill="{color}" {ring}/>'
    pts = f"{x:.1f},{y - 7:.1f} {x + 7:.1f},{y + 5.5:.1f} {x - 7:.1f},{y + 5.5:.1f}"
    return f'<polygon points="{pts}" fill="{color}" stroke-linejoin="round" {ring}/>'


def build() -> str:
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="{FONT}" role="img" aria-labelledby="t d">',
         '<title id="t">기록 수에 따른 질문당 맥락 크기</title>',
         '<desc id="d">기록이 15개에서 315개로 늘 때 전체 맥락 LLM은 4,078자에서 87,026자로 커지고, '
         'BM25 검색은 약 1,600자, 하네스는 약 330자로 일정하다.</desc>',
         f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
         f'<text x="{L}" y="44" font-size="24" font-weight="700" fill="{INK}">기록이 늘어도 하네스의 맥락은 일정하다</text>',
         f'<text x="{L}" y="72" font-size="15" fill="{INK2}">질문당 답변 LLM에 넘긴 맥락 크기(글자 수, 로그 축). 세 시스템 모두 같은 답변 모델·프롬프트.</text>']
    # 범례 (2개 이상 계열이면 항상)
    lx = L
    for _, label, color, kind, _ in SERIES:
        o.append(marker(kind, lx + 6, 96, color))
        o.append(f'<text x="{lx + 18}" y="101" font-size="14" fill="{INK2}">{label}</text>')
        lx += 44 + sum(14 if ord(c) > 0x3000 else 8 for c in label)  # 한글은 넓게, 영문·숫자는 좁게
    # y 격자·눈금
    for v in (100, 1_000, 10_000, 100_000):
        y = y_of(v)
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        o.append(f'<text x="{L - 10}" y="{y + 5:.1f}" font-size="13" fill="{MUTED}" text-anchor="end">{v:,}</text>')
    # x 눈금
    for n in RECORDS:
        o.append(f'<text x="{x_of(n):.1f}" y="{H - B + 26}" font-size="13" fill="{MUTED}" text-anchor="middle">{n}</text>')
    o.append(f'<text x="{(L + W - R) / 2:.1f}" y="{H - B + 50}" font-size="14" fill="{INK2}" '
             f'text-anchor="middle">팀 기록 수 (원래 15개 + 조건만 다른 방해 기록)</text>')
    # 선과 점
    for _, label, color, kind, vals in SERIES:
        pts = " ".join(f"{x_of(n):.1f},{y_of(v):.1f}" for n, v in zip(RECORDS, vals))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
        for n, v in zip(RECORDS, vals):
            o.append(f'<g>{marker(kind, x_of(n), y_of(v), color)}<title>{label} · 기록 {n}개 · {v:,}자</title></g>')
        # 직접 레이블: 선 끝 값 (글자는 잉크 색, 색은 옆 마커가 담당)
        ex, ey = x_of(RECORDS[-1]), y_of(vals[-1])
        o.append(f'<text x="{ex + 14:.1f}" y="{ey - 2:.1f}" font-size="14" font-weight="700" fill="{INK}">{vals[-1]:,}자</text>')
        o.append(f'<text x="{ex + 14:.1f}" y="{ey + 15:.1f}" font-size="12" fill="{INK2}">{label}</text>')
    o.append(f'<text x="{L}" y="{H - 10}" font-size="12" fill="{MUTED}">{NOTE}</text>')
    o.append("</svg>")
    return "\n".join(o)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "docs" / "figures" / "context_vs_records.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print(out)
