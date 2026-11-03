"""Mock 구현을 포함한 교체 가능한 Agent 추론 인터페이스."""

import re
from collections.abc import Mapping
from itertools import islice, product
from typing import Any, Protocol

from app.agent.contracts import (
    AgentDraft,
    AgentPlan,
    AgentRecommendationRequest,
    FashionLook,
    OutfitItem,
    ToolCall,
    ToolName,
    normalize_wardrobe_slot,
)

DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
TIME_PATTERN = re.compile(r"\b\d{2}:\d{2}\b")


class InferenceEngine(Protocol):
    """Qwen3-4B 또는 다른 모델 구현이 지켜야 하는 최소 경계."""

    def plan(self, request: AgentRecommendationRequest) -> AgentPlan: ...

    def generate(
        self,
        request: AgentRecommendationRequest,
        tool_results: Mapping[ToolName, Any],
    ) -> AgentDraft: ...


class MockInferenceEngine:
    """학습 모델 없이 Router와 Tool Calling 흐름을 검증하는 결정적 구현."""

    wardrobe_only_keywords = ("내 옷만", "옷장에서만", "보유한 옷만", "가지고 있는 옷만")
    weather_keywords = ("날씨", "기온", "비", "눈", "더위", "추위", "바람")
    weather_skip_keywords = (
        "날씨 조회하지 마",
        "날씨 다시 조회하지 말고",
        "날씨는 조회하지 마",
        "날씨 확인하지 마",
    )
    calendar_keywords = ("일정", "캘린더", "calendar")

    def plan(self, request: AgentRecommendationRequest) -> AgentPlan:
        message = request.message.lower()
        date_value = request.date or self._extract(DATE_PATTERN, request.message)
        time_value = request.time or self._extract(TIME_PATTERN, request.message)
        # 통합 5 LOOK의 4~5번 슬롯에는 옷장 정보가 반드시 필요하다.
        calls = [ToolCall(name="get_user_context"), ToolCall(name="get_wardrobe")]

        if self._contains(message, self.calendar_keywords):
            calls.append(ToolCall(name="get_calendar_events", arguments={"date": date_value}))
        if self._contains(message, self.weather_keywords) and not self._contains(
            message, self.weather_skip_keywords
        ):
            calls.append(
                ToolCall(
                    name="get_weather",
                    arguments={
                        "place": request.place,
                        "date": date_value,
                        "time": time_value,
                    },
                )
            )
        return AgentPlan(calls=calls)

    def generate(
        self,
        request: AgentRecommendationRequest,
        tool_results: Mapping[ToolName, Any],
    ) -> AgentDraft:
        preferences = self._preferences(tool_results.get("get_user_context"))
        wardrobe = self._wardrobe(tool_results.get("get_wardrobe"))
        weather = tool_results.get("get_weather")
        events = tool_results.get("get_calendar_events")

        looks = self._build_looks(request, preferences, wardrobe, weather, events)
        return AgentDraft(
            context_summary=self._context_summary(tool_results),
            looks=looks,
        )

    @staticmethod
    def _extract(pattern: re.Pattern[str], value: str) -> str | None:
        match = pattern.search(value)
        return match.group(0) if match else None

    @staticmethod
    def _contains(message: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in message for keyword in keywords)

    @staticmethod
    def _preferences(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        preference = raw.get("preference")
        return preference if isinstance(preference, dict) else {}

    @staticmethod
    def _wardrobe(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def _build_looks(
        self,
        request: AgentRecommendationRequest,
        preferences: dict[str, Any],
        wardrobe: list[dict[str, Any]],
        weather: Any,
        events: Any,
    ) -> list[FashionLook]:
        styles = self._text_list(preferences.get("preferred_styles")) or ["미니멀", "캐주얼"]
        colors = self._text_list(preferences.get("preferred_colors")) or ["네이비", "아이보리"]
        disliked = set(self._text_list(preferences.get("disliked_colors")))
        colors = [color for color in colors if color not in disliked] or ["네이비", "아이보리"]
        fit = preferences.get("preferred_fit")
        preferred_fit = fit if isinstance(fit, str) and fit.strip() else "레귤러"

        concepts = [
            f"{styles[0]} 데일리",
            f"{styles[min(1, len(styles) - 1)]} 레이어드",
            "새로운 스타일 탐색",
        ]
        roles = ["preference_best", "preference_alternative", "exploration"]
        wardrobe_only = self._contains(request.message.lower(), self.wardrobe_only_keywords)

        looks: list[FashionLook] = []
        for index in range(3):
            if wardrobe_only:
                looks.append(
                    FashionLook(
                        look_id=index + 1,
                        role=roles[index],
                        status="unavailable",
                        style=None,
                        items=[],
                        reason=(
                            "사용자가 내 옷만으로 추천해 달라고 요청하여 "
                            "일반 의류를 제안하지 않습니다."
                        ),
                    )
                )
                continue

            top = self._generic_item(
                "top",
                "셔츠" if index < 2 else "니트 베스트",
                colors[index % len(colors)],
                preferred_fit,
            )
            bottom = self._generic_item(
                "bottom",
                "데님 팬츠" if index != 1 else "테이퍼드 슬랙스",
                "인디고" if index != 1 else "차콜",
                preferred_fit,
            )
            shoes = self._generic_item(
                "shoes",
                "로우탑 스니커즈" if index < 2 else "로퍼",
                "화이트" if index < 2 else "블랙",
                "레귤러",
            )
            items = [top, bottom, shoes]
            outer = self._weather_outer(weather, preferred_fit)
            if outer is not None:
                items.append(outer)

            looks.append(
                FashionLook(
                    look_id=index + 1,
                    role=roles[index],
                    status="available",
                    style=concepts[index],
                    items=items,
                    reason=self._reason(index, weather, events),
                )
            )
        looks.extend(self._wardrobe_looks(wardrobe, preferences))
        return looks

    @staticmethod
    def _text_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @staticmethod
    def _group_wardrobe(wardrobe: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in wardrobe:
            normalized = normalize_wardrobe_slot(item.get("category"))
            if normalized:
                grouped.setdefault(normalized, []).append(item)
        return grouped

    def _wardrobe_looks(
        self, wardrobe: list[dict[str, Any]], preferences: dict[str, Any]
    ) -> list[FashionLook]:
        disliked = {color.lower() for color in self._text_list(preferences.get("disliked_colors"))}
        eligible = [
            item
            for item in wardrobe
            if isinstance(item.get("item_id"), int)
            and not isinstance(item["item_id"], bool)
            and item["item_id"] > 0
            and str(item.get("color", "")).lower() not in disliked
        ]
        grouped = self._group_wardrobe(eligible)
        combinations = islice(
            product(
                grouped.get("top", []),
                grouped.get("bottom", []),
                grouped.get("shoes", []),
            ),
            2,
        )
        looks: list[FashionLook] = []
        for index, combination in enumerate(combinations, start=4):
            items = [
                self._owned_item(item, slot)
                for item, slot in zip(combination, ("top", "bottom", "shoes"), strict=True)
            ]
            looks.append(
                FashionLook(
                    look_id=index,
                    role="wardrobe_best" if index == 4 else "wardrobe_alternative",
                    status="available",
                    style="보유 의류 기본 조합" if index == 4 else "보유 의류 대안 조합",
                    items=items,
                    reason="등록된 의류만 사용해 완성 코디를 구성했습니다.",
                )
            )
        while len(looks) < 2:
            index = len(looks) + 4
            looks.append(
                FashionLook(
                    look_id=index,
                    role="wardrobe_best" if index == 4 else "wardrobe_alternative",
                    status="unavailable",
                    style=None,
                    items=[],
                    reason=(
                        "등록된 상의·하의·신발로 완성 코디를 만들 수 없습니다."
                        if index == 4
                        else "등록된 의류로 서로 다른 두 번째 완성 코디를 만들 수 없습니다."
                    ),
                )
            )
        return looks

    @staticmethod
    def _owned_item(item: dict[str, Any], slot: str) -> OutfitItem:
        return OutfitItem(
            slot=slot,
            name=f"{item.get('color') or '미지정'} {item.get('type') or '의류'}",
            item_id=item["item_id"],
        )

    @staticmethod
    def _generic_item(slot: str, item_type: str, color: str, fit: str) -> OutfitItem:
        return OutfitItem(slot=slot, name=f"{color} {fit} {item_type}", item_id=None)

    def _weather_outer(self, weather: Any, fit: str) -> OutfitItem | None:
        if not isinstance(weather, dict):
            return None
        precipitation = str(weather.get("precipitation_type", "")).strip().lower()
        probability = weather.get("precipitation_probability")
        temperature = weather.get("temperature_c")
        if precipitation not in {"", "none", "없음", "강수없음"} or (
            isinstance(probability, int) and probability >= 50
        ):
            return self._generic_item("outer", "발수 재킷", "네이비", fit)
        if isinstance(temperature, int | float) and temperature <= 5:
            return self._generic_item("outer", "보온 코트", "차콜", fit)
        if isinstance(temperature, int | float) and temperature >= 28:
            return None
        return self._generic_item("outer", "라이트 블루종", "네이비", fit)

    @staticmethod
    def _reason(index: int, weather: Any, events: Any) -> str:
        parts = [
            "사용자 선호를 가장 직접적으로 반영했습니다."
            if index == 0
            else "선호 범위 안에서 다른 조합을 제안했습니다."
            if index == 1
            else "기존 선호와 조화를 유지하면서 새로운 실루엣을 제안했습니다."
        ]
        if isinstance(weather, dict):
            parts.append("조회된 날씨 조건을 아우터 선택에 반영했습니다.")
        if isinstance(events, list):
            parts.append(f"일정 {len(events)}건을 확인했습니다.")
        return " ".join(parts)

    @staticmethod
    def _context_summary(tool_results: Mapping[ToolName, Any]) -> str:
        parts: list[str] = []
        if "get_user_context" in tool_results:
            parts.append("프로필과 패션 취향")
        wardrobe = tool_results.get("get_wardrobe")
        if isinstance(wardrobe, list):
            parts.append(f"옷장 {len(wardrobe)}개 항목")
        if "get_weather" in tool_results:
            parts.append("목적지 날씨")
        events = tool_results.get("get_calendar_events")
        if isinstance(events, list):
            parts.append(f"일정 {len(events)}건")
        return f"{', '.join(parts)}을(를) 반영했습니다."
