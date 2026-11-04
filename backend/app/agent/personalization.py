"""Structured recommendation attributes and deterministic preference ranking."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALIASES = {
    "styles": {"미니멀": "minimal", "캐주얼": "casual", "클래식": "classic", "스트리트": "street"},
    "colors": {
        "네이비": "navy",
        "아이보리": "ivory",
        "화이트": "white",
        "흰색": "white",
        "블랙": "black",
        "검정": "black",
        "검정색": "black",
        "차콜": "charcoal",
        "그레이": "gray",
        "grey": "gray",
        "인디고": "indigo",
        "빨강": "red",
        "빨간색": "red",
        "레드": "red",
        "블루": "blue",
        "파랑": "blue",
    },
    "fits": {"레귤러": "regular", "와이드": "wide", "오버핏": "oversized", "슬림": "slim"},
}


def normalize_tag(dimension: str, value: str) -> str:
    value = "_".join(value.strip().lower().replace("-", " ").split())
    return ALIASES.get(dimension, {}).get(value, value)


class LookFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    styles: list[str] = Field(default_factory=list, max_length=8)
    fits: list[str] = Field(default_factory=list, max_length=8)
    colors: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("styles", "fits", "colors")
    @classmethod
    def canonical_tags(cls, values: list[str], info) -> list[str]:
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("속성은 1~100자의 구조화된 값이어야 합니다.")
        return list(dict.fromkeys(normalize_tag(info.field_name, value) for value in values))


def feedback_preferences(context: Any) -> dict:
    """Never overwrite manual settings; use learned scores to rank their choices."""
    if not isinstance(context, dict):
        context = {}
    preferences = dict(context.get("preference") or {})
    summary = context.get("feedback_summary") or {}
    weights = summary.get("weights", {})
    preferences["_weights"] = weights
    defaults = {
        "styles": ["미니멀", "캐주얼"],
        "colors": ["네이비", "아이보리", "블랙", "화이트", "그레이", "블루", "brown"],
    }
    for dimension, field in (("styles", "preferred_styles"), ("colors", "preferred_colors")):
        scores = weights.get(dimension, {})
        choices = (
            preferences.get(field)
            or [tag for tag, score in scores.items() if score > 0]
            or defaults[dimension]
        )
        preferences[field] = sorted(
            choices, key=lambda tag: scores.get(normalize_tag(dimension, tag), 0), reverse=True
        )
    blocked = {normalize_tag("colors", value) for value in preferences.get("disliked_colors", [])}
    colors = [
        value
        for value in preferences["preferred_colors"]
        if normalize_tag("colors", value) not in blocked
    ]
    preferences["preferred_colors"] = colors or [
        value for value in defaults["colors"] if normalize_tag("colors", value) not in blocked
    ]
    if not preferences.get("preferred_fit"):
        scores = weights.get("fits", {})
        preferences["preferred_fit"] = next(
            (tag for tag in sorted(scores, key=scores.get, reverse=True) if scores[tag] > 0),
            "레귤러",
        )
    return preferences


def wardrobe_rank(item: dict, preferences: dict) -> tuple[int, int]:
    """Manual preference matches take precedence over learned ranking."""
    color = normalize_tag("colors", str(item.get("color") or ""))
    fit = normalize_tag("fits", str(item.get("fit") or ""))
    preferred = {normalize_tag("colors", value) for value in preferences["preferred_colors"]}
    manual = int(color in preferred) + int(
        fit == normalize_tag("fits", preferences["preferred_fit"])
    )
    scores = preferences.get("_weights", {})
    learned = scores.get("colors", {}).get(color, 0) + scores.get("fits", {}).get(fit, 0)
    return manual, learned
