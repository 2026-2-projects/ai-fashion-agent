import { validateLook } from "./recommendation-model.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATUSES = new Set(["available", "unavailable"]);
const FEEDBACK_TYPES = new Set(["like", "dislike"]);

export const FEEDBACK_REASON_LABELS = Object.freeze({
  color: "색상이 아쉬워요",
  fit: "핏이 아쉬워요",
  not_my_style: "내 스타일이 아니에요",
  too_dressed_up: "너무 격식 있어요",
  too_plain: "너무 평범해요",
  too_casual: "너무 캐주얼해요",
  weather: "날씨·계절에 맞지 않아요",
  occasion: "일정·장소에 맞지 않아요",
  combination: "옷의 조합이 아쉬워요",
  other: "기타 (직접 입력)",
});
export const FEEDBACK_TEXT_LIMIT = 300;

const INVALID_TEXT_CONTROLS = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/;

class InteractionValidationError extends Error {}
function invalid(message = "코디의 평가·저장 상태를 확인하지 못했어요. 다시 불러와 주세요.") {
  throw new InteractionValidationError(message);
}
function object(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function uuid(value) { return typeof value === "string" && UUID.test(value); }
function lookId(value) { return Number.isSafeInteger(value) && value >= 1 && value <= 5; }
function positiveId(value) { return Number.isSafeInteger(value) && value > 0; }
function reason(value) { return typeof value === "string" && Object.hasOwn(FEEDBACK_REASON_LABELS, value); }
function sameRecommendation(value, expected) {
  return uuid(value) && uuid(expected) && value.toLowerCase() === expected.toLowerCase();
}

function validateReasonText(value) {
  if (typeof value !== "string" || INVALID_TEXT_CONTROLS.test(value)) invalid("기타 사유를 올바른 텍스트로 입력해 주세요.");
  const text = value.trim();
  if (!text) invalid("기타 사유를 입력해 주세요.");
  if (Array.from(text).length > FEEDBACK_TEXT_LIMIT) invalid("기타 사유는 300자 이내로 입력해 주세요.");
  return text;
}

/** Other feedback adds explicit text; the original reason-only payload stays compatible. */
export function buildFeedbackPayload(type, selectedReason = null, reasonText = null) {
  if (!FEEDBACK_TYPES.has(type)) invalid("좋아요 또는 싫어요를 선택해 주세요.");
  if (selectedReason !== null && !reason(selectedReason)) invalid("싫어요 사유를 다시 선택해 주세요.");
  if (type === "like" && selectedReason !== null) invalid("좋아요에는 싫어요 사유를 함께 보낼 수 없어요.");
  if (selectedReason === "other") {
    return { feedback_type: type, reason: selectedReason, reason_text: validateReasonText(reasonText) };
  }
  if (reasonText !== null && reasonText !== undefined) invalid("직접 입력한 사유는 기타를 선택했을 때만 보낼 수 있어요.");
  return { feedback_type: type, reason: selectedReason };
}

/** Validate the requested identity before a returned state is attached to any card. */
export function validateInteraction(data, recommendationId, requestedLookId) {
  if (!object(data) || !lookId(requestedLookId)
      || !sameRecommendation(data.recommendation_id, recommendationId)
      || data.look_id !== requestedLookId || !STATUSES.has(data.status)
      || !(data.feedback === null || FEEDBACK_TYPES.has(data.feedback))
      || !(data.reason === null || reason(data.reason)) || typeof data.saved !== "boolean") invalid();
  if (data.feedback !== "dislike" && data.reason !== null) invalid();
  if (data.reason === "other") {
    if (validateReasonText(data.reason_text) !== data.reason_text) invalid();
  } else if (data.reason_text !== undefined && data.reason_text !== null) invalid();
  if (data.status === "unavailable" && (data.feedback !== null || data.reason !== null || data.saved)) invalid();
  return data;
}

/** The response may arrive in any order, but must describe every LOOK exactly once. */
export function validateInteractions(data, recommendationId, looks = null) {
  if (!object(data) || !sameRecommendation(data.recommendation_id, recommendationId)
      || !Array.isArray(data.looks) || data.looks.length !== 5) invalid();
  let expected = null;
  if (looks !== null) {
    if (!Array.isArray(looks) || looks.length !== 5) invalid();
    expected = new Map();
    for (const look of looks) {
      if (!object(look) || !lookId(look.look_id) || !STATUSES.has(look.status) || expected.has(look.look_id)) invalid();
      expected.set(look.look_id, look.status);
    }
  }
  const seen = new Set();
  for (const state of data.looks) {
    if (!object(state) || seen.has(state.look_id)) invalid();
    validateInteraction(state, recommendationId, state.look_id);
    if (expected !== null && expected.get(state.look_id) !== state.status) invalid();
    seen.add(state.look_id);
  }
  return data;
}

function safeTitle(value, fallback) {
  const cleaned = typeof value === "string"
    ? value.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ").trim()
    : "";
  return Array.from(cleaned || fallback).slice(0, 100).join("");
}

// A datetime from a legacy row may lack a timezone. Preserve it without inventing one.
function safeDateTime(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-](\d{2}):(\d{2}))?$/.exec(value);
  if (!match) return null;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, offsetHourText = "00", offsetMinuteText = "00"] = match;
  const [year, month, day, hour, minute, second, offsetHour, offsetMinute] =
    [yearText, monthText, dayText, hourText, minuteText, secondText, offsetHourText, offsetMinuteText].map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]
      || hour > 23 || minute > 59 || second > 59 || offsetHour > 23 || offsetMinute > 59
      || !Number.isFinite(Date.parse(value))) return null;
  return value;
}

/** Legacy rows remain visible, while only validated linked snapshots expose actions/images. */
export function validateSavedOutfits(data) {
  const fail = () => invalid("저장한 코디 목록을 확인하지 못했어요. 다시 불러와 주세요.");
  if (!Array.isArray(data)) fail();
  const ids = new Set(), targets = new Set();
  return data.map(row => {
    if (!object(row) || !positiveId(row.id) || ids.has(row.id)
        || !(row.recommendation_id === null || uuid(row.recommendation_id))
        || !(row.look_id === null || lookId(row.look_id))
        || !(row.title === null || typeof row.title === "string") || typeof row.created_at !== "string") fail();
    ids.add(row.id);
    const recommendationId = row.recommendation_id === null ? null : row.recommendation_id.toLowerCase();
    const linked = recommendationId !== null && row.look_id !== null;
    if (linked) {
      const target = `${recommendationId}:${row.look_id}`;
      if (targets.has(target)) fail();
      targets.add(target);
    }

    let look = null, notice = "";
    if (!linked) {
      notice = "이전 방식으로 저장한 코디예요. 원본 추천 연결이 없어 상세 보기와 저장 취소를 지원하지 않아요.";
    } else {
      try {
        // Reuse exactly the recommendation card's slot, source and image URL contract.
        validateLook(row.outfit_data, row.look_id - 1);
        if (row.outfit_data.status !== "available") {
          notice = "현재 사용할 수 없는 코디예요. 상세 보기와 저장 취소를 지원하지 않아요.";
        } else {
          look = row.outfit_data;
        }
      } catch {
        notice = "저장된 코디 상세 정보를 확인하지 못했어요. 이 항목의 상세 보기와 저장 취소를 지원하지 않아요.";
      }
    }
    const createdAt = safeDateTime(row.created_at);
    if (createdAt === null) notice += `${notice ? " " : ""}저장 날짜를 확인하지 못했어요.`;
    return {
      id: row.id,
      recommendation_id: recommendationId,
      look_id: row.look_id,
      title: safeTitle(row.title, look ? safeTitle(look.style, "저장한 코디") : "저장한 코디"),
      created_at: createdAt,
      look,
      manageable: linked && look !== null,
      notice,
    };
  });
}

/** HTTP failures use local messages; server internals and untrusted raw errors stay hidden. */
export function interactionError(error) {
  if (error?.status === 401) return "로그인이 만료됐어요. 다시 로그인해 주세요.";
  if (error?.status === 403) return "요청을 확인하지 못했어요. 새로고침 후 다시 시도해 주세요. 계속되면 다시 로그인해 주세요.";
  if (error?.status === 404) return "이 추천을 찾을 수 없어요. 현재 계정에서 새 추천을 요청해 주세요.";
  if (error?.status === 409) return "현재 사용할 수 없는 코디예요. 새 추천을 요청해 주세요.";
  if (error?.status === 422) return "선택한 코디와 평가 사유를 확인하고 다시 시도해 주세요.";
  if (error?.status === 429) return "요청이 일시적으로 제한됐어요. 잠시 후 다시 시도해 주세요.";
  if (typeof error?.status === "number" && error.status >= 500) return "평가·저장 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
  if (error instanceof InteractionValidationError) return error.message;
  if (error?.status === 0 || error?.name === "TypeError" || error?.name === "AbortError") {
    return "서버에 연결하지 못했어요. 연결 상태를 확인한 뒤 다시 불러와 주세요.";
  }
  return "코디의 평가·저장 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
}
