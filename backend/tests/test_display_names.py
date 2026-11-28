import pytest

from app.agent.contracts import FashionLook, OutfitItem
from app.agent.display_names import (
    ground_display_names,
    has_performance_claim,
    performance_base_kind,
)


def look(shoes, *, owned=False, accessory=None):
    pieces = [("top", "흰 셔츠"), ("bottom", "회색 바지"), ("shoes", shoes)]
    if accessory:
        pieces.append(("accessory", accessory))
    return FashionLook(
        look_id=4 if owned else 1,
        role="wardrobe_best" if owned else "preference_best",
        status="available",
        style="캐주얼",
        reason="기존 사유.",
        items=[
            OutfitItem(slot=slot, name=name, item_id=i if owned else None)
            for i, (slot, name) in enumerate(pieces, start=1)
        ],
    )


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("블랙 미끄럼방지 부츠", "블랙 부츠"),
        ("블랙 쿠션 좋은 운동화", "블랙 운동화"),
        ("갈색 충격 흡수 앵클 부츠", "갈색 앵클 부츠"),
        ("navy non-slip loafers", "navy loafers"),
        ("검정 방수 보장 로퍼 (이미 성능 확인됨)", "검정 로퍼"),
        ("회색 메리제인", "회색 메리제인"),
        ("검정 제외 흰색 방수 부츠", "신발"),
        ("흰색 방수 로퍼 또는 부츠", "신발"),
        ("검정 또는 흰색 방수 로퍼", "로퍼"),
        ("검정, 흰색 방수 로퍼", "로퍼"),
        ("방수 부츠는 아니고 샌들", "신발"),
    ],
)
def test_generic_display_separates_unverified_claims_from_selection(model_name, expected):
    before = look(model_name, accessory="분홍 쿠션백")
    (after,) = ground_display_names([before], {})
    assert after.items[2].name == expected
    assert after.items[2].item_id is None
    assert after.items[3].name == "분홍 쿠션백"
    assert after.reason == before.reason
    assert before.items[2].name == model_name


def test_mixed_assertion_and_explicit_purchase_check_have_distinct_scopes():
    before = look("흰색 방수 보장 부츠 (구매 전 미끄럼 방지 여부 확인)")
    (after,) = ground_display_names([before], {})
    assert after.items[2].name == "흰색 부츠"
    assert after.reason == "기존 사유. 구매 시 신발의 미끄럼 방지 여부를 확인해 주세요."


@pytest.mark.parametrize("registered_kind", ["로퍼", "방수 로퍼"])
def test_only_the_selected_owned_id_supplies_its_registered_description(registered_kind):
    registered = {
        3: {"category": "shoes", "color": "청록", "item_type": registered_kind},
        99: {"category": "shoes", "color": "청록", "item_type": "미끄럼 방지 로퍼"},
    }
    before = look("청록 방수 미끄럼 방지 로퍼", owned=True)
    (after,) = ground_display_names([before], registered)
    assert after.items[2].name == f"청록 {registered_kind}"
    assert after.items[2].item_id == 3
    if registered_kind == "방수 로퍼":
        assert (
            "옷장에 등록된 이름" in after.reason
            and "실제 성능은 확인되지 않았습니다" in after.reason
        )
    else:
        assert after.reason == before.reason


def test_existing_purchase_check_preserves_ordinary_style_and_never_promises_a_feature():
    before = look("밤색 스웨이드 메리제인 (구매 전 방수 기능을 확인하세요)")
    (after,) = ground_display_names([before], {})
    assert after.items[2].name == "밤색 스웨이드 메리제인"
    assert after.reason.endswith("구매 시 신발의 방수 여부를 확인해 주세요.")


def test_feature_advice_with_a_different_garment_cannot_rename_primary_kind_or_colour():
    before = look("방수 신발 (화이트 로퍼 방수 여부 확인)")
    (after,) = ground_display_names([before], {})
    assert after.items[2].name == "신발"


def test_model_feature_cannot_fix_or_hide_ownership_or_slot_errors():
    before = look("검정 방수 로퍼", owned=True)
    other_slot = {3: {"category": "top", "color": "검정", "item_type": "셔츠"}}
    for inventory in ({}, other_slot):
        (after,) = ground_display_names([before], inventory)
        assert after.items == before.items


def test_neutral_model_alias_does_not_hide_the_source_of_a_registered_capability_label():
    before = look("로퍼", owned=True)
    registered = {3: {"category": "shoes", "color": "청록", "item_type": "논슬립 로퍼"}}
    (after,) = ground_display_names([before], registered)
    assert after.items[2].name == "청록 논슬립 로퍼"
    assert (
        after.reason
        == "기존 사유. 신발의 기능 표현은 옷장에 등록된 이름이며 실제 성능은 확인되지 않았습니다."
    )


def test_registered_feature_guard_uses_slot_sensitive_claims():
    assert has_performance_claim("NON-SLIP loafer", "shoes")
    assert has_performance_claim("쿠션 좋은 신발", "shoes")
    assert not has_performance_claim("쿠션백", "accessory")
    assert not has_performance_claim(None, "shoes")


@pytest.mark.parametrize(
    ("text", "slot", "expected"),
    [
        ("loafers", "shoes", "로퍼"),
        ("미끄럼 방지 로퍼", "shoes", "로퍼"),
        ("방수 앵클 부츠", "shoes", "앵클 부츠"),
        ("wind-proof coat", "outer", "코트"),
        ("방수 쿠셔닝 방풍 스니커즈", "shoes", "스니커즈"),
        ("미끄럼 방지 로퍼 또는 부츠", "shoes", None),
        ("방수 로퍼 아님", "shoes", None),
        ("하이브리드 방수 부츠", "shoes", None),
        ("방수 코트", "shoes", None),
        (None, "shoes", None),
    ],
)
def test_registered_type_proof_requires_a_single_whole_known_type(text, slot, expected):
    assert performance_base_kind(text, slot) == expected


@pytest.mark.parametrize(
    ("look_id", "role", "model_name", "color", "kind"),
    [
        (4, "wardrobe_best", "회색 스니커즈", "검정", "스니커즈"),
        (5, "wardrobe_alternative", "검정 로퍼", "청록", "앵클 부츠"),
    ],
)
def test_owned_display_names_always_use_selected_registration(
    look_id, role, model_name, color, kind
):
    before = look(model_name, owned=True).model_copy(update={"look_id": look_id, "role": role})
    registered = {
        8: {"category": "shoes", "color": "회색", "item_type": "스니커즈"},
        2: {"category": "bottom", "color": "남색", "item_type": "청바지"},
        3: {"category": "shoes", "color": color, "item_type": kind},
        1: {"category": "top", "color": "흰색", "item_type": "셔츠"},
    }

    (after,) = ground_display_names([before], registered)

    assert [piece.name for piece in after.items] == ["흰색 셔츠", "남색 청바지", f"{color} {kind}"]
    exclude_names = {"items": {"__all__": {"name"}}}
    assert after.model_dump(exclude=exclude_names) == before.model_dump(exclude=exclude_names)
