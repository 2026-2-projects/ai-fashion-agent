"""Input-aware, optional clarification before the existing five-LOOK agent.

The browser sends the user's original message and the structured place/date/time
fields together. The policy infers only straightforward facts, distinguishes
contradictions from missing information, and asks at most two questions. A Qwen
adapter may replace this policy without changing the HTTP API.

This module never calls external services, accesses private user records, or
writes a database. The caller still uses the existing authenticated/CSRF-checked
``/agent/clarify`` endpoint and only calls ``/agent/recommend`` when ready.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable, Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.contracts import AgentRecommendationRequest

QuestionId = Literal[
    "destination", "occasion", "place_conflict", "date_conflict", "time_conflict",
]
_CONFLICT_IDS = ("place_conflict", "date_conflict", "time_conflict")
_POLICY = "rules_v2"
_MAX_QUESTIONS = 2


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    answer: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def normalize_answer(self) -> "ClarificationAnswer":
        self.answer = self.answer.strip()
        if not self.answer:
            raise ValueError("답변을 입력해 주세요.")
        return self


class ClarificationRequest(AgentRecommendationRequest):
    """Stateless: the user repeats their original request and follow-up answers."""

    answers: list[ClarificationAnswer] = Field(default_factory=list, max_length=2)
    skip: bool = False

    @model_validator(mode="after")
    def check_fields(self) -> "ClarificationRequest":
        ids = [a.question_id for a in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("같은 질문에는 한 번만 답변할 수 있습니다.")
        if self.date:
            try:
                date.fromisoformat(self.date)
            except ValueError as exc:
                raise ValueError("날짜는 실제 존재하는 YYYY-MM-DD 형식이어야 합니다.") from exc
        if self.time:
            _parse_24hour_time(self.time, required=True)
        return self


class ClarificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["ask", "ready"]
    question_id: QuestionId | None = None
    question: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    resolved_request: AgentRecommendationRequest
    policy: Literal["rules_v2"] = _POLICY


class ClarificationPolicy(Protocol):
    def inspect(self, request: ClarificationRequest) -> ClarificationResponse: ...


# Only recognize locations when they are written as independent location names,
# not as substrings of places like '전주대학교'. This is intentionally a heuristic,
# not a geocoder. A genuine unknown destination can be typed in the form.
_CITY_NAMES = (
    "서울", "인천", "수원", "성남", "용인", "고양", "부천", "안양", "안산",
    "강릉", "속초", "춘천", "원주", "평창", "동해", "삼척", "양양",
    "부산", "대구", "대전", "광주", "울산", "세종", "전주", "익산",
    "군산", "완주", "김제", "남원", "정읍", "부안", "고창", "무주",
    "청주", "충주", "천안", "아산", "공주", "보령", "서산",
    "포항", "경주", "구미", "안동", "영주", "창원", "진주", "통영",
    "거제", "김해", "제주", "서귀포", "도쿄", "오사카", "교토",
    "후쿠오카", "삿포로", "나고야", "홍콩", "타이베이", "방콕",
    "싱가포르", "하노이", "다낭", "파리", "런던", "뉴욕", "로마",
)
_CITY_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z])(?P<city>" + "|".join(map(re.escape, sorted(_CITY_NAMES, key=len, reverse=True)))
    + r")(?:시|도)?(?=$|[\s,.!?~]|에서|으로|로|에|을|를|까지|부터|쪽)",
)
_TRAVEL_WORDS = ("여행", "출장", "관광", "캠핑", "나들이", "놀러", "바다 보러")
_WEATHER_WORDS = ("날씨", "기온", "비 올", "눈 올", "더위", "추위", "바람")
_FORMAL_WORDS = ("격식", "포멀", "정장", "중요한 자리", "중요한 모임", "중요한 행사", "공식 행사", "행사에")
_KNOWN_OCCASIONS = (
    "결혼식", "면접", "장례식", "돌잔치", "졸업식", "입학식", "소개팅",
    "회사 회의", "비즈니스 미팅", "공식 발표", "세미나", "학회", "취업 설명회",
    "시상식", "상견례", "조문", "축하연", "송년회", "연말 파티",
)
_DATE_ISO = re.compile(r"(?<!\d)(20\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)")
_DATE_RELATIVE = re.compile(r"오늘|내일|모레")
_TIME_EXPLICIT = re.compile(
    r"(?<!\d)(?:(?P<meridiem>오전|오후)\s*)?"
    r"(?P<hour>\d{1,2})(?::(?P<colon_minute>\d{2})|시(?!간)(?:\s*(?P<ko_minute>\d{1,2})분?)?)"
)


def _parse_24hour_time(value: str, *, required: bool = False) -> str | None:
    match = re.fullmatch(r"(\d{2}):(\d{2})", value)
    if match and int(match.group(1)) < 24 and int(match.group(2)) < 60:
        return value
    if required:
        raise ValueError("시간은 00:00부터 23:59까지 입력해 주세요.")
    return None


def _message_locations(text: str) -> list[str]:
    found: list[str] = []
    for match in _CITY_PATTERN.finditer(text):
        place = match.group("city")
        if place not in found:
            found.append(place)
    return found


def _same_place(form_value: str, message_value: str) -> bool:
    a = re.sub(r"\s+", "", form_value).casefold()
    b = re.sub(r"\s+", "", message_value).casefold()
    if a == b:
        return True
    # '부산광역시', '강릉역' and '전주대학교' may be valid more specific
    # destinations in the same city. A different city is still a conflict.
    return any(city in a and city == b for city in _CITY_NAMES)


def _message_date(text: str, today: date) -> str | None:
    explicit = _DATE_ISO.search(text)
    if explicit:
        try:
            return date(*map(int, explicit.groups())).isoformat()
        except ValueError:
            return None
    relative = _DATE_RELATIVE.search(text)
    if relative:
        delta = {"오늘": 0, "내일": 1, "모레": 2}[relative.group()]
        return (today + timedelta(days=delta)).isoformat()
    return None


def _message_time(text: str) -> str | None:
    for found in _TIME_EXPLICIT.finditer(text):
        raw_hour = int(found.group("hour"))
        raw_minute = found.group("colon_minute") or found.group("ko_minute") or "0"
        minute = int(raw_minute)
        meridiem = found.group("meridiem")
        if minute >= 60:
            continue
        if meridiem:
            if raw_hour not in range(1, 13):
                continue
            hour = (raw_hour % 12) + (12 if meridiem == "오후" else 0)
        else:
            hour = raw_hour
            if hour > 23:
                continue
            # Bare '1시' is context-dependent in Korean. Do not silently
            # infer 01:00 or 13:00. Colon notation means explicit 24h.
            if found.group("colon_minute") is None and 1 <= hour <= 12:
                continue
        return f"{hour:02d}:{minute:02d}"
    return None


def _has_occasion(message: str) -> bool:
    return any(item in message for item in _KNOWN_OCCASIONS)


def _append_notes(message: str, notes: list[str]) -> str:
    if not notes:
        return message
    updated = message + "\n[사용자가 확정한 정보 — 앞선 문장보다 우선] " + "; ".join(notes)
    if len(updated) > 1000:
        raise ValueError("정보를 합치면 요청이 1,000자를 초과합니다. 요청 내용을 조금 줄여 주세요.")
    return updated


def _ask(question_id: QuestionId, question: str, suggestions: list[str], resolved: AgentRecommendationRequest) -> ClarificationResponse:
    return ClarificationResponse(
        decision="ask", question_id=question_id, question=question,
        suggestions=suggestions, resolved_request=resolved,
    )


class RuleBasedClarificationPolicy:
    """Ask only when a missing fact or contradiction changes a recommendation.

    Form inputs are authoritative on 'just recommend' or when the optional
    two-question budget is exhausted. Conflict choices are checked against
    *this* request's two possible values, never accepted as arbitrary input.
    """

    def __init__(self, today: Callable[[], date] | None = None) -> None:
        self._today = today or (lambda: datetime.now(ZoneInfo("Asia/Seoul")).date())

    def inspect(self, request: ClarificationRequest) -> ClarificationResponse:
        base_message = request.message
        answers = {a.question_id: a.answer for a in request.answers}
        locations = _message_locations(base_message)
        mentioned_place = locations[0] if len(locations) == 1 else None
        mentioned_date = _message_date(base_message, self._today())
        mentioned_time = _message_time(base_message)
        place, chosen_date, chosen_time = request.place, request.date, request.time
        notes: list[str] = []

        # An explicit place/date/time field is used if the natural text is
        # silent. If the two disagree, ask for a choice (do not overwrite one).
        conflict_items: list[tuple[QuestionId, str, str, str]] = []
        if place and mentioned_place and not _same_place(place, mentioned_place):
            conflict_items.append(("place_conflict", "장소", place, mentioned_place))
        if chosen_date and mentioned_date and chosen_date != mentioned_date:
            conflict_items.append(("date_conflict", "날짜", chosen_date, mentioned_date))
        if chosen_time and mentioned_time and chosen_time != mentioned_time:
            conflict_items.append(("time_conflict", "시간", chosen_time, mentioned_time))

        for question_id in _CONFLICT_IDS:
            if question_id in answers and not any(item[0] == question_id for item in conflict_items):
                raise ValueError("이전에 확인하던 입력 정보가 변경됐어요. 처음부터 다시 추천해 주세요.")

        for qid, label, form_value, text_value in conflict_items:
            suggestions = [f"입력창: {form_value}", f"요청 문장: {text_value}"]
            selected = answers.get(qid)
            if selected is None and not request.skip and len(request.answers) < _MAX_QUESTIONS:
                provisional = AgentRecommendationRequest(
                    message=base_message, place=place, date=chosen_date, time=chosen_time,
                )
                return _ask(qid, f"{label} 정보가 서로 달라요. 어느 쪽을 사용할까요?", suggestions, provisional)
            if selected is not None and selected not in suggestions:
                raise ValueError(f"{label}는 표시된 두 옵션 중 하나를 선택해 주세요.")
            final_value = text_value if selected == suggestions[1] else form_value
            if qid == "place_conflict":
                place = final_value
            elif qid == "date_conflict":
                chosen_date = final_value
            else:
                chosen_time = final_value
            notes.append(f"{label}: {final_value}")

        # A single unambiguous value in natural text is useful when the input
        # fields are empty. Do not guess when several cities appear.
        if not place and mentioned_place:
            place = mentioned_place
        if not chosen_date and mentioned_date:
            chosen_date = mentioned_date
        if not chosen_time and mentioned_time:
            chosen_time = mentioned_time

        if "destination" in answers:
            if place and request.place and not _same_place(place, answers["destination"]):
                raise ValueError("장소 입력창이 변경됐어요. 다시 추천을 시작해 주세요.")
            place = answers["destination"]
            notes.append("여행·활동 지역: " + place)
        if "occasion" in answers:
            notes.append("행사 종류: " + answers["occasion"])

        needs_place = (
            any(word in base_message for word in _TRAVEL_WORDS + _WEATHER_WORDS)
            and not place
            and "날씨 조회하지 마" not in base_message
            and "날씨는 조회하지 마" not in base_message
        )
        needs_occasion = any(word in base_message for word in _FORMAL_WORDS) and not (
            _has_occasion(base_message) or "occasion" in answers
        )

        # Ambiguity after exhausting the budget is resolved conservatively;
        # missing time/date alone NEVER forces a question.
        can_ask = not request.skip and len(request.answers) < _MAX_QUESTIONS
        resolved_message = _append_notes(base_message, notes)
        if can_ask and needs_place and "destination" not in answers:
            return _ask(
                "destination", "여행지나 날씨를 확인할 지역을 알려주시겠어요?",
                ["서울", "전주", "부산", "강릉"],
                AgentRecommendationRequest(message=resolved_message, place=place, date=chosen_date, time=chosen_time),
            )
        if can_ask and needs_occasion and "occasion" not in answers:
            return _ask(
                "occasion", "격식의 정도를 맞출 수 있도록 어떤 자리인지 알려주세요.",
                ["결혼식", "면접", "회사 행사", "가족 모임"],
                AgentRecommendationRequest(message=resolved_message, place=place, date=chosen_date, time=chosen_time),
            )

        if needs_place and any(w in base_message for w in _WEATHER_WORDS):
            # MockInferenceEngine otherwise schedules get_weather with
            # place=None. This suffix instructs its explicit opt-out handling.
            resolved_message = _append_notes(
                resolved_message, ["장소가 없어 날씨 조회하지 마. 기본 취향으로 추천해줘."]
            )
        return ClarificationResponse(
            decision="ready",
            resolved_request=AgentRecommendationRequest(
                message=resolved_message, place=place, date=chosen_date, time=chosen_time,
            ),
        )
