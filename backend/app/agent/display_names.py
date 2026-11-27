"""Ground functional product descriptions after model selection and reason validation."""

import re

from app.agent.contracts import FashionLook
from app.agent.reasons import SLOT_LABELS
from app.agent.requirements import COLORS, KINDS, aliases, color_name, kind_name, normalized

# A generic LOOK has neither a product ID nor verified product specifications.
# Limit the intervention to recognizable performance claims, preserving ordinary style labels.
FUNCTIONS = {
    "미끄럼 방지": re.compile(r"미끄럼\s*방지|논[\s-]*슬립|(?:non|anti)[\s-]*slip", re.I),
    "쿠셔닝": re.compile(r"쿠셔닝|쿠션|충격\s*흡수|cushion(?:ed|ing)?|shock[\s-]*absorb", re.I),
    "방수": re.compile(r"방수|워터\s*프루프|water[\s-]*proof", re.I),
    "발수": re.compile(r"발수|water[\s-]*repellen(?:t|cy)", re.I),
    "방풍": re.compile(r"방풍|wind[\s-]*proof", re.I),
    "자외선 차단": re.compile(r"(?:자외선|uv)\s*차단", re.I),
}
# The scope of a request to check ends at the named property. A confirmed claim or
# an unrelated instruction elsewhere in the label does not become purchase advice.
CHECK_AFTER = re.compile(
    r"^\s*(?:기능|성능|처리)?\s*(?:여부|정도)?\s*(?:을|를)?\s*"
    r"확인(?:해\s*주세요|하세요|할\s*것|(?:이\s*)?\s*필요|(?=\s*[)\],.;]|\s*$))"
)


def _known_words(words):
    options = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:" + options + r")(?!\w)", re.I)


COLOR = _known_words(COLORS)
KIND = {slot: _known_words(aliases(groups)) for slot, groups in KINDS.items()}


def _feature_matches(text: str, slot: str):
    return [
        (label, match)
        for label, pattern in FUNCTIONS.items()
        if label != "쿠셔닝" or slot == "shoes"
        for match in pattern.finditer(text)
    ]


def has_performance_claim(text: object, slot: str) -> bool:
    """Does a free-text label mention a supported property with no independent spec field?"""
    return bool(_feature_matches(normalized(text), slot))


def performance_base_kind(text: object, slot: str) -> str | None:
    """Only accept a known whole type after removing the supported capability vocabulary."""
    base = normalized(text)
    matches = sorted(_feature_matches(base, slot), key=lambda entry: entry[1].start(), reverse=True)
    for _, match in matches:
        base = base[: match.start()] + " " + base[match.end() :]
    base = normalized(base)
    if slot in KIND and KIND[slot].fullmatch(base):
        return kind_name(base)
    return None


_NEGATION = re.compile(
    r"제외|아니|아닌|아님|말고|빼고|금지|않|없는|없이|\b(?:not|except|excluding|without|no)\b"
)


def _generic_name(piece, features):
    primary = re.split(r"[（(]", piece.name, maxsplit=1)[0].strip()
    main = normalized(primary)
    slot_name = SLOT_LABELS[piece.slot]
    if _NEGATION.search(main):
        return slot_name
    kinds = {kind_name(m[0]): m[0] for m in KIND[piece.slot].finditer(main)}
    if len(kinds) > 1:
        return slot_name
    colors = {color_name(m[0]): m[0] for m in COLOR.finditer(main)}
    if len(colors) <= 1 and main and all(match.start() >= len(main) for _, match in features):
        return primary
    item_type = next(iter(kinds.values()), slot_name)
    if len(colors) == 1:
        return f"{next(iter(colors.values()))} {item_type}"
    return item_type


def ground_display_names(looks: list[FashionLook], registered: dict) -> list[FashionLook]:
    result = []
    for look in looks:
        items = []
        checks = []
        registered_feature_slots = []
        for piece in look.items:
            name = normalized(piece.name)
            features = _feature_matches(name, piece.slot)
            if look.look_id <= 3 and features:
                # Structured generic names also serve as shopping/image search queries.
                label = _generic_name(piece, features)
                for feature, match in features:
                    if CHECK_AFTER.match(name[match.end() :]):
                        checks.append(f"{SLOT_LABELS[piece.slot]}의 {feature} 여부")
            elif look.look_id >= 4:
                source = registered.get(piece.item_id)
                if not source or source.get("category") != piece.slot:
                    # Leave ownership/slot errors for the existing service validation.
                    items.append(piece)
                    continue
                if has_performance_claim(source.get("item_type"), piece.slot):
                    registered_feature_slots.append(SLOT_LABELS[piece.slot])
                elif not features:
                    items.append(piece)
                    continue
                label = " ".join(
                    v.strip()
                    for v in (source.get("color"), source.get("item_type"))
                    if isinstance(v, str) and v.strip()
                )
                label = label or SLOT_LABELS[piece.slot]
            else:
                items.append(piece)
                continue
            items.append(piece.model_copy(update={"name": label}))
        reason = look.reason
        if checks:
            reason += " 구매 시 " + ", ".join(dict.fromkeys(checks)) + "를 확인해 주세요."
        if registered_feature_slots:
            slots = "·".join(registered_feature_slots)
            reason += (
                f" {slots}의 기능 표현은 옷장에 등록된 이름이며 실제 성능은 확인되지 않았습니다."
            )
        result.append(look.model_copy(update={"items": items, "reason": reason}))
    return result
