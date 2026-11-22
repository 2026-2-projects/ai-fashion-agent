const LOOK_ROLES = [
  "preference_best", "preference_alternative", "exploration",
  "wardrobe_best", "wardrobe_alternative",
];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const LOOK_ROLE_LABELS = Object.freeze({
  preference_best: "취향에 맞는 추천",
  preference_alternative: "취향 안의 다른 조합",
  exploration: "새로운 스타일 탐색",
  wardrobe_best: "내 옷으로 만든 추천",
  wardrobe_alternative: "내 옷으로 만든 다른 조합",
});
export const SLOT_LABELS = Object.freeze({
  top: "상의", bottom: "하의", shoes: "신발", outer: "아우터", accessory: "액세서리",
});
export const TOOL_LABELS = Object.freeze({
  get_user_context: "프로필·취향", get_wardrobe: "나만의 옷장",
  get_weather: "날씨 조회", get_calendar_events: "Google 일정 조회",
});
export const IMAGE_STATUS_LABELS = Object.freeze({
  found: "이미지 확인", not_found: "이미지 없음",
  provider_unavailable: "상품 이미지를 불러오지 못했어요.",
  provider_disabled: "상품 이미지 검색이 설정되지 않았어요.",
});

function object(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function text(value) { return typeof value === "string" && value.trim().length > 0; }
function nullableText(value) { return value === null || typeof value === "string"; }
function positiveId(value) { return Number.isSafeInteger(value) && value > 0; }
function known(mapping, key) { return typeof key === "string" && Object.hasOwn(mapping, key); }
function invalid(message = "추천 응답을 확인하지 못했어요. 다시 시도해 주세요.") { throw new Error(message); }
function inputError(field, message) { const error = new Error(message); error.field = field; throw error; }

function validDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1];
}

/** Only explicit structured values are added; natural-language tool selection stays on the server. */
export function buildRecommendationRequest(raw = {}) {
  const message = typeof raw.message === "string" ? raw.message.trim() : "";
  if (!message || Array.from(message).length > 1000) inputError("message", "추천 요청을 1~1000자로 입력해 주세요.");
  const result = { message };
  for (const field of ["place", "date", "time"]) {
    const value = raw[field];
    if (value === undefined || value === null || value === "") continue;
    if (typeof value !== "string") inputError(field, "입력한 장소·날짜·시간을 확인해 주세요.");
    const normalized = value.trim();
    if (!normalized) continue;
    if (field === "place" && Array.from(normalized).length > 100) inputError(field, "장소를 100자 이하로 입력해 주세요.");
    if (field === "date" && !validDate(normalized)) inputError(field, "실제 날짜를 YYYY-MM-DD 형식으로 입력해 주세요.");
    if (field === "time" && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(normalized)) inputError(field, "시간을 00:00~23:59 범위로 입력해 주세요.");
    result[field] = normalized;
  }
  return result;
}

/** External images/links must be HTTPS and must not point at local network addresses. */
export function safeExternalUrl(value) {
  if (typeof value !== "string" || !/^https:\/\//i.test(value)
      || value.trim() !== value || /[\u0000-\u001f\u007f\\]/.test(value)) return null;
  let url;
  try { url = new URL(value); } catch { return null; }
  if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return null;
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local") || !host.includes(".")) return null;
  // URL canonicalization resolves alternate IPv4 spellings before this check.
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
    const [a, b] = host.split(".").map(Number);
    if (a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254)
        || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
        || (a === 100 && b >= 64 && b <= 127)) return null;
  }
  if (host.startsWith("[")) return null;
  return value;
}

export function safeWardrobeImageUrl(value, itemId) {
  return positiveId(itemId) && value === `/api/v1/wardrobe/${itemId}/image` ? value : null;
}

export function validateLook(look, index) {
  if (!object(look) || look.look_id !== index + 1 || look.role !== LOOK_ROLES[index]
      || !["available", "unavailable"].includes(look.status) || !text(look.reason) || !Array.isArray(look.items)) invalid();
  if (look.status === "unavailable") {
    if (look.style !== null || look.items.length !== 0) invalid();
    return;
  }
  if (!text(look.style) || look.items.length < 3 || look.items.length > 5) invalid();
  const slots = new Set(), ids = new Set();
  for (const item of look.items) {
    if (!object(item) || !known(SLOT_LABELS, item.slot) || slots.has(item.slot) || !text(item.name)) invalid();
    slots.add(item.slot);
    if (look.look_id <= 3) {
      if (item.item_id !== null || item.image_url !== null) invalid();
    } else {
      if (!positiveId(item.item_id) || ids.has(item.item_id)) invalid();
      ids.add(item.item_id);
      if (item.image_url !== null && !safeWardrobeImageUrl(item.image_url, item.item_id)) invalid();
    }
  }
  if (!["top", "bottom", "shoes"].every(slot => slots.has(slot))) invalid();
}

export function validateRecommendation(data) {
  if (!object(data) || data.type !== "fashion_recommendation" || data.action !== "generate_five_looks"
      || !text(data.context_summary) || typeof data.recommendation_id !== "string" || !UUID.test(data.recommendation_id)
      || !Array.isArray(data.looks) || data.looks.length !== 5 || !Array.isArray(data.called_tools)
      || data.called_tools.length > 4 || data.called_tools.some(name => !known(TOOL_LABELS, name))
      || new Set(data.called_tools).size !== data.called_tools.length
      || !["get_user_context", "get_wardrobe"].every(name => data.called_tools.includes(name))) invalid();
  data.looks.forEach(validateLook);
  if (data.looks[4].status === "available") {
    if (data.looks[3].status !== "available") invalid();
    const combination = look => look.items.map(item => `${item.slot}:${item.item_id}`).sort().join("|");
    if (combination(data.looks[3]) === combination(data.looks[4])) invalid();
  }
  return data;
}

/** Match every resolved item to the original look before exposing its image or link. */
export function validateLookImages(data, recommendationId, look) {
  const fail = () => invalid("이미지 응답이 요청한 코디와 일치하지 않아요. 다시 확인해 주세요.");
  if (!object(data) || !object(look) || typeof recommendationId !== "string" || !UUID.test(recommendationId)
      || typeof data.recommendation_id !== "string" || data.recommendation_id.toLowerCase() !== recommendationId.toLowerCase()
      || data.look_id !== look.look_id || data.look_status !== look.status || !Array.isArray(data.items)) fail();
  if (look.status === "unavailable") {
    if (data.resolution_status !== "not_applicable" || data.items.length !== 0) fail();
    return data;
  }
  if (look.status !== "available" || !Array.isArray(look.items) || data.items.length !== look.items.length
      || !["complete", "partial"].includes(data.resolution_status)) fail();
  const wardrobe = look.look_id >= 4;
  data.items.forEach((item, index) => {
    const original = look.items[index];
    if (!object(item) || item.slot !== original.slot || item.name !== original.name
        || item.origin !== (wardrobe ? "wardrobe" : "google_shopping") || !known(IMAGE_STATUS_LABELS, item.status)) fail();
    if (wardrobe && !["found", "not_found"].includes(item.status)) fail();
    if (item.status !== "found") {
      if (item.image !== null) fail();
      return;
    }
    const image = item.image;
    if (!object(image) || !text(image.title) || !nullableText(image.source_name) || !nullableText(image.source_url)
        || image.provider !== (wardrobe ? "user_wardrobe" : "serpapi_google_shopping")
        || image.rights_status !== (wardrobe ? "user_provided" : "unverified")) fail();
    if (wardrobe) {
      if (!safeWardrobeImageUrl(image.url, original.item_id) || image.url !== original.image_url || image.source_url !== null) fail();
    } else if (!safeExternalUrl(image.url) || (image.source_url !== null && !safeExternalUrl(image.source_url))) fail();
  });
  const complete = data.items.every(item => item.status === "found");
  if (data.resolution_status !== (complete ? "complete" : "partial")) fail();
  return data;
}

export function recommendationError(error, operation = "recommend") {
  if (operation === "images" && error?.status === 404) return "이 추천의 이미지를 찾을 수 없어요. 현재 계정에서 새 추천을 요청해 주세요.";
  if (error?.status === 429) return "요청이 일시적으로 제한됐어요. 잠시 후 다시 시도해 주세요.";
  if (typeof error?.message === "string" && error.message.trim()) return error.message;
  return operation === "images" ? "이미지를 불러오지 못했어요. 잠시 후 다시 시도해 주세요." : "추천 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
}
