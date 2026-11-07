"""D15 1층 규칙 부품 테스트: 인용 검증 (D3)."""
from harness_v2.quote import auto_quote, find_quote

SOURCE = "실험 결과 AUC는 0.842였다.\n\n학습률을 낮춰도 성능은 개선되지 않았다. 결측치는 중앙값 대체를 채택했다."


def test_exact_quote_passes_with_position():
    result = find_quote(SOURCE, "중앙값 대체를 채택했다")
    assert result.ok
    assert SOURCE[result.start:result.end] == "중앙값 대체를 채택했다"


def test_changed_number_rejected():
    result = find_quote(SOURCE, "AUC는 0.843였다")
    assert not result.ok
    assert "0.842" in result.nearest


def test_flipped_negation_rejected():
    assert not find_quote(SOURCE, "성능은 개선되었다").ok


def test_whitespace_only_difference_passes():
    result = find_quote(SOURCE, "0.842였다. 학습률을   낮춰도")
    assert result.ok
    assert SOURCE[result.start:result.end] == "0.842였다.\n\n학습률을 낮춰도"


def test_empty_quote_rejected():
    assert not find_quote(SOURCE, "   ").ok


def test_short_source_auto_quoted():
    assert auto_quote("짧은 노트") == "짧은 노트"


def test_long_source_not_auto_quoted():
    assert auto_quote("가" * 301) is None
    assert auto_quote("가" * 300) is not None
