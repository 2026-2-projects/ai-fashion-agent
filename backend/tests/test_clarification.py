"""Step 11: user request + structured fields + minimal necessary clarification.

Uses an injected calendar date so relative dates are deterministic. No database
or external models/services are required.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.agent.clarification import (
    ClarificationAnswer,
    ClarificationRequest,
    RuleBasedClarificationPolicy,
)


@pytest.fixture
def rules():
    return RuleBasedClarificationPolicy(today=lambda: date(2026, 11, 22))


def req(message, *, answers=None, **kwargs):
    return ClarificationRequest(message=message, answers=answers or [], **kwargs)


def reply(qid, value):
    return ClarificationAnswer(question_id=qid, answer=value)


@pytest.mark.parametrize("message", [
    "오늘 학교에 갈 캐주얼 코디 추천해줘", "그냥 아무거나 편한 코디 추천해줘",
    "내 옷만으로 코디 추천해줘", "전주대학교 수업에 갈 코디 추천해줘",
    "서울 여행 가는데 편하게 입고 싶어", "회사 면접에 입을 격식 있는 옷 추천해줘",
])
def test_no_avoidable_question(rules, message):
    result = rules.inspect(req(message))
    assert result.decision == "ready"
    assert result.resolved_request.message == message


def test_form_place_prevents_destination_question(rules):
    result = rules.inspect(req(
        "내일 여행 가는데 편하게 입을 코디", place="강릉", date="2026-11-23", time="13:00",
    ))
    assert result.decision == "ready"
    assert result.resolved_request.place == "강릉"
    assert result.resolved_request.date == "2026-11-23"
    assert result.resolved_request.time == "13:00"


def test_natural_place_and_date_fill_empty_form_without_question(rules):
    result = rules.inspect(req("내일 강릉으로 여행 가는데 편한 코디 추천해줘"))
    assert result.decision == "ready"
    assert result.resolved_request.place == "강릉"
    assert result.resolved_request.date == "2026-11-23"


def test_structured_fields_silently_override_missing_not_conflicting_data(rules):
    result = rules.inspect(req("오늘 대학에 입을 캐주얼 룩", place="전주대학교", time="01:00"))
    assert result.decision == "ready"
    assert result.resolved_request.place == "전주대학교"
    assert result.resolved_request.time == "01:00"


def test_place_conflict_requires_explicit_choice(rules):
    base = req("강릉으로 여행 가는데 편한 룩 추천", place="부산")
    first = rules.inspect(base)
    assert first.decision == "ask" and first.question_id == "place_conflict"
    assert "입력창: 부산" in first.suggestions
    assert "요청 문장: 강릉" in first.suggestions
    chosen_text = rules.inspect(req(base.message, place="부산", answers=[reply("place_conflict", "요청 문장: 강릉")]))
    assert chosen_text.decision == "ready"
    assert chosen_text.resolved_request.place == "강릉"
    assert "장소: 강릉" in chosen_text.resolved_request.message
    chosen_form = rules.inspect(req(base.message, place="부산", answers=[reply("place_conflict", "입력창: 부산")]))
    assert chosen_form.decision == "ready"
    assert chosen_form.resolved_request.place == "부산"
    assert "장소: 부산" in chosen_form.resolved_request.message


def test_place_conflict_not_triggered_by_more_specific_form_location(rules):
    result = rules.inspect(req("전주에서 모임 갈 때 입을 옷", place="전주대학교"))
    assert result.decision == "ready"
    assert result.resolved_request.place == "전주대학교"


def test_invalid_conflict_choice_cannot_override_form(rules):
    with pytest.raises(ValueError, match="두 옵션"):
        rules.inspect(req("강릉 여행", place="부산", answers=[reply("place_conflict", "베를린")]))
    with pytest.raises(ValueError, match="변경됐어요"):
        rules.inspect(req("강릉 여행", place="강릉", answers=[reply("place_conflict", "입력창: 부산")]))


def test_date_conflict_has_two_choices(rules):
    first = rules.inspect(req("내일 여행 가는 날씨에 맞춰", place="강릉", date="2026-11-25"))
    assert first.question_id == "date_conflict"
    assert "입력창: 2026-11-25" in first.suggestions
    selected = rules.inspect(req("내일 여행 가는 날씨에 맞춰", place="강릉", date="2026-11-25", answers=[reply("date_conflict", "요청 문장: 2026-11-23")]))
    assert selected.decision == "ready"
    assert selected.resolved_request.date == "2026-11-23"
    assert "날짜: 2026-11-23" in selected.resolved_request.message


@pytest.mark.parametrize(("text", "hour"), [
    ("오전 1시", "01:00"), ("오후 1시", "13:00"),
    ("오전 12시", "00:00"), ("오후 12시 30분", "12:30"),
    ("23시 45분", "23:45"), ("13:00", "13:00"),
])
def test_natural_time_is_normalized_to_24hour(rules, text, hour):
    result = rules.inspect(req(f"{text}에 입을 코디 추천해줘"))
    assert result.decision == "ready"
    assert result.resolved_request.time == hour


def test_ambiguous_single_digit_time_is_not_guessed(rules):
    assert rules.inspect(req("1시에 입을 코디 추천해줘")).resolved_request.time is None
    assert rules.inspect(req("1시간 동안 걸을 때 편한 코디 추천해줘")).resolved_request.time is None


def test_time_conflict_asks_and_respects_choice(rules):
    first = rules.inspect(req("오후 1시에 입을 코디", time="01:00"))
    assert first.question_id == "time_conflict"
    selected = rules.inspect(req("오후 1시에 입을 코디", time="01:00", answers=[reply("time_conflict", "요청 문장: 13:00")]))
    assert selected.decision == "ready"
    assert selected.resolved_request.time == "13:00"


def test_missing_time_date_never_prompts_on_general_request(rules):
    result = rules.inspect(req("오늘 데일리 룩 추천해줘", place="전주"))
    assert result.decision == "ready"


def test_unknown_trip_destination_one_question_and_merge(rules):
    first = rules.inspect(req("내일 여행 가는데 편하게 입고 싶어"))
    assert first.question_id == "destination"
    second = rules.inspect(req(first.resolved_request.message, answers=[reply("destination", "강릉")]))
    assert second.decision == "ready"
    assert second.resolved_request.place == "강릉"
    assert "강릉" in second.resolved_request.message


def test_formal_occasion_one_question(rules):
    first = rules.inspect(req("격식 있는 자리에 갈 코디 추천"))
    assert first.question_id == "occasion"
    answer = rules.inspect(req("격식 있는 자리에 갈 코디 추천", answers=[reply("occasion", "면접")]))
    assert answer.decision == "ready"
    assert "행사 종류: 면접" in answer.resolved_request.message


def test_multiple_questions_bounded(rules):
    prompt = "중요한 행사로 해외 여행 가는데 날씨도 봐줘"
    first = rules.inspect(req(prompt))
    assert first.question_id == "destination"
    second = rules.inspect(req(prompt, answers=[reply("destination", "도쿄")]))
    assert second.question_id == "occasion"
    third = rules.inspect(req(prompt, answers=[reply("destination", "도쿄"), reply("occasion", "가족 결혼식")]))
    assert third.decision == "ready"
    assert third.resolved_request.place == "도쿄"


def test_multiple_unresolved_conflicts_honor_question_budget(rules):
    prompt = "내일 강릉에 오후 1시 여행"
    first = rules.inspect(req(prompt, place="부산", date="2026-11-25", time="01:00"))
    assert first.question_id == "place_conflict"
    second = rules.inspect(req(prompt, place="부산", date="2026-11-25", time="01:00", answers=[reply("place_conflict", "입력창: 부산")]))
    assert second.question_id == "date_conflict"
    third = rules.inspect(req(prompt, place="부산", date="2026-11-25", time="01:00", answers=[reply("place_conflict", "입력창: 부산"), reply("date_conflict", "입력창: 2026-11-25")]))
    assert third.decision == "ready"
    # The third conflict is settled by the explicitly filled field.
    assert third.resolved_request.time == "01:00"
    assert "시간: 01:00" in third.resolved_request.message


def test_skip_keeps_explicit_form_and_goes_ready(rules):
    result = rules.inspect(req("강릉 여행", place="부산", skip=True))
    assert result.decision == "ready"
    assert result.resolved_request.place == "부산"
    assert "장소: 부산" in result.resolved_request.message


def test_skip_unknown_weather_place_does_not_break_mock_engine(rules):
    result = rules.inspect(req("날씨 고려해서 코디 추천해줘", skip=True))
    assert result.decision == "ready" and result.resolved_request.place is None
    assert "날씨 조회하지 마" in result.resolved_request.message


def test_invalid_fields_and_duplicate_questions_are_rejected():
    with pytest.raises(ValidationError):
        req("여행", time="26:99")
    with pytest.raises(ValidationError):
        req("여행", date="2026-02-30")
    with pytest.raises(ValidationError):
        req("여행", answers=[reply("occasion", "결혼식"), reply("occasion", "면접")])


def test_length_limit_is_not_silently_truncated(rules):
    prompt = "해외 여행 " + "가" * 985
    assert rules.inspect(req(prompt)).decision == "ask"
    with pytest.raises(ValueError, match="1,000자"):
        rules.inspect(req(prompt, answers=[reply("destination", "강릉")]))
