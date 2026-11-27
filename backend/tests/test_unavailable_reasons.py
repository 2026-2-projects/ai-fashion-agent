"""Unavailable owned LOOKs must explain only what the registered fields establish."""

import pytest
from test_qwen_service_scenarios import WARDROBE, _recommend, _unavailable

from app.agent.contracts import AgentRecommendationRequest


@pytest.mark.parametrize(
    ("request_text", "registered_type", "registered_color", "expected_text"),
    [
        ("청록 샌들이 필수야.", "플랫슈즈", "청록", "‘샌들’ 종류가 없습니다"),
        ("청록 샌들이 필수야.", "샌들", "검정", "모두 다른 색으로 등록"),
        ("청록 샌들이 필수야.", "샌들", None, "‘청록 샌들’에 맞는지 확인할 수 없습니다"),
        ("청록 샌들이 필수야.", None, "청록", "‘청록 샌들’에 맞는지 확인할 수 없습니다"),
        ("빨간 샌들이 필수야.", "샌들", "red", "등록한 비선호색"),
        ("로퍼는 제외해.", "로퍼", "베이지", "요청에서 제외하신 ‘로퍼’"),
        ("방수 샌들이 필수야.", "샌들", "회색", "확인되지 않은 속성"),
        ("은색 코트가 좋겠어.", "샌들", "회색", "이번 요청에 맞는 옷장 조합을 확인하지 못했습니다"),
    ],
)
def test_unavailable_reason_uses_known_causes_only(
    monkeypatch, request_text, registered_type, registered_color, expected_text
):
    request = AgentRecommendationRequest(message=request_text)
    shoes = {**WARDROBE[2], "type": registered_type, "color": registered_color}
    looks = [_unavailable(index) for index in range(1, 6)]
    result, _ = _recommend(monkeypatch, request, [*WARDROBE[:2], shoes], looks)
    assert [look.status for look in result.looks[3:]] == ["unavailable", "unavailable"]
    assert all(expected_text in look.reason for look in result.looks[3:])
