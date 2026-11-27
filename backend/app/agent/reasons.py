"""Render Qwen explanations from the selected LOOKs and the original tool facts."""

from collections.abc import Mapping
from typing import Any

from app.agent.contracts import (
    AgentRecommendationRequest,
    FashionLook,
    ToolName,
    normalize_wardrobe_slot,
)
from app.agent.inference import wardrobe_only_requested
from app.agent.requirements import Constraints, ItemCondition, color_name, kind_name

SLOT_LABELS = {
    "top": "상의",
    "bottom": "하의",
    "shoes": "신발",
    "outer": "아우터",
    "accessory": "액세서리",
}
REQUIRED = ("top", "bottom", "shoes")


def _label(item: dict, slot: str) -> str:
    fields = [item.get("color"), item.get("type")]
    return (
        " ".join(value.strip() for value in fields if isinstance(value, str) and value.strip())
        or SLOT_LABELS[slot]
    )


def _generic_reason(look: FashionLook, first: FashionLook, wardrobe_only: bool) -> str:
    if look.status == "unavailable":
        if wardrobe_only:
            return "보유한 옷만 요청하셔서 일반 코디 제안은 생략했습니다."
        return "이번 요청에 제안할 일반 코디를 구성하지 못했습니다."
    slots = {piece.slot for piece in look.items}
    if look.look_id != first.look_id and first.status == "available":
        first_slots = {piece.slot for piece in first.items}
        added = [label for slot, label in SLOT_LABELS.items() if slot in slots - first_slots]
        if added:
            return f"첫 번째 일반 코디에 없던 {'·'.join(added)} 품목을 포함한 제안입니다."
    labels = "·".join(label for slot, label in SLOT_LABELS.items() if slot in slots)
    return f"{labels}로 구성한 일반 코디를 제안합니다."


def _stock(slot: str, items: list[dict]) -> str:
    names = ", ".join(_label(item, slot) for item in items[:2])
    if len(items) > 2:
        names += f" 외 {len(items) - 2}개"
    return f"등록된 {SLOT_LABELS[slot]} {len(items)}개({names})"


def _required_item_reason(
    condition: ItemCondition, inventory: dict[str, list[dict]], disliked: set[str]
) -> str | None:
    slot = condition.slot
    if slot is None or condition.excluded:
        return None
    label = " ".join(filter(None, (condition.color, condition.kind or SLOT_LABELS[slot])))
    items = inventory.get(slot, [])
    if not items:
        return f"필수 품목은 ‘{label}’입니다. 옷장에 등록된 {SLOT_LABELS[slot]} 품목이 없습니다."

    attributes = [(kind_name(item.get("type")), color_name(item.get("color"))) for item in items]
    if any(condition.allows(slot, kind, color) for kind, color in attributes):
        if condition.color and condition.color in disliked:
            return f"필수 품목 ‘{label}’의 색상이 등록한 비선호색이어서 해당 품목을 제외했습니다."
        return None
    # A missing field could still match. Only assert absence when all records rule it out.
    if any(
        condition.allows(slot, kind or condition.kind, color or condition.color)
        for kind, color in attributes
    ):
        return (
            f"등록된 {SLOT_LABELS[slot]}의 종류·색 정보만으로는 "
            f"필수 조건 ‘{label}’에 맞는지 확인할 수 없습니다."
        )
    stock = _stock(slot, items)
    kind_only = ItemCondition(slot, kind=condition.kind)
    if (
        condition.kind
        and all(kind for kind, _ in attributes)
        and not any(kind_only.allows(slot, kind, color) for kind, color in attributes)
    ):
        return f"필수 품목은 ‘{label}’입니다. {stock} 중 ‘{condition.kind}’ 종류가 없습니다."
    if (
        condition.color
        and condition.kind
        and any(kind_only.allows(slot, kind, color) for kind, color in attributes)
    ):
        return (
            f"필수 품목은 ‘{label}’입니다. {stock} 중 "
            "종류가 맞는 품목은 모두 다른 색으로 등록되어 있습니다."
        )
    return f"필수 품목은 ‘{label}’입니다. {stock} 중 해당 조건에 맞는 품목이 없습니다."


def _unavailable_owned(
    look: FashionLook,
    first_owned: FashionLook,
    inventory: dict[str, list[dict]],
    constraints: Constraints,
    disliked: set[str],
) -> str:
    missing = [SLOT_LABELS[slot] for slot in REQUIRED if not inventory.get(slot)]
    if missing:
        return f"등록된 {'·'.join(missing)} 품목이 없어 옷장 코디를 완성할 수 없습니다."
    if constraints.unverified:
        return (
            "등록된 종류·색 정보만으로 요청하신 필수·제외 조건을 확인할 수 없습니다. "
            "기능·소재 등 확인되지 않은 속성은 추천 근거로 사용하지 않았습니다."
        )
    if look.look_id != first_owned.look_id and first_owned.status == "available":
        return "이번 요청에서 첫 번째 옷장 코디와 다른 조합을 제시하지 못했습니다."
    for condition in constraints.items:
        reason = _required_item_reason(condition, inventory, disliked)
        if reason:
            return reason
    for condition in constraints.items:
        if not condition.excluded:
            continue
        for slot in REQUIRED:
            if condition.slot not in (None, slot):
                continue
            target = ItemCondition(slot, kind=condition.kind, color=condition.color)
            if all(
                target.allows(slot, kind_name(p.get("type")), color_name(p.get("color")))
                for p in inventory[slot]
            ):
                label = " ".join(
                    filter(None, (condition.color, condition.kind or SLOT_LABELS[slot]))
                )
                stock = _stock(slot, inventory[slot])
                return f"{stock} 모두 요청에서 제외하신 ‘{label}’에 해당합니다."
    return "이번 요청에 맞는 옷장 조합을 확인하지 못했습니다."


def grounded_reasons(
    looks: list[FashionLook],
    request: AgentRecommendationRequest,
    tool_results: Mapping[ToolName, Any],
    *,
    constraints: Constraints,
) -> list[FashionLook]:
    by_id = {}
    inventory: dict[str, list[dict]] = {}
    for item in tool_results.get("get_wardrobe", []):
        if (
            not isinstance(item, dict)
            or type(item.get("item_id")) is not int
            or item["item_id"] <= 0
        ):
            continue
        slot = normalize_wardrobe_slot(item.get("category"))
        if slot:
            by_id[item["item_id"]] = item
            inventory.setdefault(slot, []).append(item)

    context = tool_results.get("get_user_context")
    preference = context.get("preference") if isinstance(context, dict) else None
    colors = preference.get("preferred_colors") if isinstance(preference, dict) else None
    preferred = (
        {c.strip().casefold() for c in colors if isinstance(c, str) and c.strip()}
        if isinstance(colors, list)
        else set()
    )
    excluded_colors = preference.get("disliked_colors") if isinstance(preference, dict) else None
    disliked = {color_name(c) for c in excluded_colors or [] if c}
    only = wardrobe_only_requested(request.message)
    result = []
    for look in looks:
        if look.look_id <= 3:
            reason = _generic_reason(look, looks[0], only)
        elif look.status == "unavailable":
            reason = _unavailable_owned(look, looks[3], inventory, constraints, disliked)
        else:
            # Ownership and slot validation still run in AgentService before any result is returned.
            selected = [by_id.get(piece.item_id, {}) for piece in look.items]
            labels = [
                _label(item, piece.slot) for item, piece in zip(selected, look.items, strict=True)
            ]
            reason = f"옷장에 등록된 {', '.join(labels)} 조합입니다."
            matches = dict.fromkeys(
                color.strip()
                for item in selected
                if isinstance(color := item.get("color"), str)
                and color.strip().casefold() in preferred
            )
            if matches:
                reason += f" 등록한 선호색과 일치하는 색은 {', '.join(matches)}입니다."
        result.append(look.model_copy(update={"reason": reason}))
    return result
