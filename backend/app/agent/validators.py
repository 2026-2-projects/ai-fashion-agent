"""Shared model JSON validation and authenticated wardrobe validation."""

from app.agent.contracts import AgentDraft, FashionLook, normalize_wardrobe_slot


class AgentResultError(Exception):
    """Generated content does not match the authenticated user's wardrobe."""


def validate_agent_json(raw: AgentDraft | dict | str) -> AgentDraft:
    if isinstance(raw, AgentDraft):
        # A mutated Pydantic instance must be checked again, including nested LOOKs.
        result = AgentDraft.model_validate_json(raw.model_dump_json(), strict=True)
        result._look_features = dict(raw._look_features)
        return result
    if isinstance(raw, str):
        return AgentDraft.model_validate_json(raw, strict=True)
    return AgentDraft.model_validate(raw, strict=True)


def validate_owned_look(look: FashionLook, wardrobe: object) -> FashionLook:
    if not isinstance(wardrobe, list):
        raise AgentResultError("옷장 Tool 결과가 올바르지 않습니다.")
    by_id = {
        item["item_id"]: item
        for item in wardrobe
        if isinstance(item, dict) and type(item.get("item_id")) is int
    }
    items = []
    for piece in look.items:
        source = by_id.get(piece.item_id)
        if source is None or normalize_wardrobe_slot(source.get("category")) != piece.slot:
            raise AgentResultError("옷장 LOOK에 등록되지 않은 항목이 포함되었습니다.")
        if piece.image_url is not None:
            raise AgentResultError("모델이 옷장 사진 URL을 직접 제공할 수 없습니다.")
        image = source.get("image")
        if image is not None and (not isinstance(image, str) or not image.strip()):
            raise AgentResultError("옷장 Tool의 사진 주소가 올바르지 않습니다.")
        name = piece.name
        if source.get("color") and source.get("type"):
            name = f"{source['color']} {source['type']}"
        items.append(piece.model_copy(update={"name": name, "image_url": image}))
    return look.model_copy(update={"items": items})


def validate_wardrobe_looks(looks: list[FashionLook], wardrobe: object) -> list[FashionLook]:
    if not isinstance(wardrobe, list):
        raise AgentResultError("옷장 Tool 결과가 올바르지 않습니다.")
    combinations = set()
    enriched = list(looks[:3])
    for look in looks[3:]:
        if look.status == "unavailable":
            enriched.append(look)
            continue
        checked = validate_owned_look(look, wardrobe)
        combination = {(piece.slot, piece.item_id) for piece in checked.items}
        frozen = frozenset(combination)
        if frozen in combinations:
            raise AgentResultError("옷장 LOOK 4와 5는 다른 조합이어야 합니다.")
        combinations.add(frozen)
        enriched.append(checked)
    return enriched
