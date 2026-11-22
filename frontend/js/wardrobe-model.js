export const CATEGORY_OPTIONS = [
  ["top", "상의"],
  ["bottom", "하의"],
  ["outer", "아우터"],
  ["shoes", "신발"],
  ["accessory", "액세서리"],
];

export const FIT_OPTIONS = [
  ["slim", "슬림"],
  ["regular", "레귤러"],
  ["wide", "와이드"],
  ["oversized", "오버사이즈"],
];

export const SEASON_OPTIONS = [
  ["spring", "봄"],
  ["summer", "여름"],
  ["fall", "가을"],
  ["winter", "겨울"],
];

export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_IMAGE_PIXELS = 16_000_000;

const CATEGORY_ALIASES = new Map(CATEGORY_OPTIONS.flatMap(([value, label]) => [
  [value, value], [label, value],
]));
const CATEGORY_LABELS = new Map(CATEGORY_OPTIONS);
const FIT_LABELS = new Map(FIT_OPTIONS);
const SEASON_LABELS = new Map(SEASON_OPTIONS);
const COLOR_LABELS = new Map([
  ["black", "블랙"], ["white", "화이트"], ["navy", "네이비"],
  ["beige", "베이지"], ["gray", "그레이"], ["grey", "그레이"],
  ["brown", "브라운"], ["dark_brown", "다크 브라운"],
  ["black_white", "블랙·화이트"], ["indigo", "인디고"],
  ["charcoal", "차콜"], ["ivory", "아이보리"], ["blue", "블루"],
  ["red", "레드"], ["pink", "핑크"], ["yellow", "옐로"],
  ["green", "그린"], ["purple", "퍼플"], ["orange", "오렌지"],
]);
const PHOTO_TYPES = new Map([
  ["jpg", "image/jpeg"], ["jpeg", "image/jpeg"],
  ["png", "image/png"], ["webp", "image/webp"],
]);
const TEXT_FIELDS = [
  ["category", "분류", 50],
  ["type", "종류", 100],
  ["color", "색상", 50],
  ["fit", "핏", 50],
];

export class WardrobeValidationError extends Error {
  constructor(field, message) {
    super(message);
    this.name = "WardrobeValidationError";
    this.field = String(field);
  }
}

export function normalizeCategory(value) {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  return CATEGORY_ALIASES.get(normalized) || "other";
}

export function categoryLabel(value) {
  return CATEGORY_LABELS.get(normalizeCategory(value))
    || (typeof value === "string" ? value : "");
}

function optionLabel(value, labels) {
  if (typeof value !== "string") return "";
  return labels.get(value.trim().toLowerCase()) || value;
}

export function fitLabel(value) {
  return optionLabel(value, FIT_LABELS);
}

export function seasonLabel(value) {
  return optionLabel(value, SEASON_LABELS);
}

/** Validate the response shape without changing existing custom metadata. */
export function validateItem(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)
      || !Number.isSafeInteger(data.item_id) || data.item_id <= 0
      || TEXT_FIELDS.some(([field]) => typeof data[field] !== "string")
      || !Array.isArray(data.seasons) || data.seasons.some((season) => typeof season !== "string")
      || !(data.image_url === null || typeof data.image_url === "string")
      || typeof data.created_at !== "string" || typeof data.updated_at !== "string") {
    throw new Error("옷장 응답을 확인하지 못했습니다. 새로고침 후 다시 시도해 주세요.");
  }
  return data;
}

/** Build only fields accepted by WardrobeCreate/WardrobeUpdate. */
export function validateWardrobeInput(raw) {
  const payload = {};
  for (const [field, label, limit] of TEXT_FIELDS) {
    const value = typeof raw?.[field] === "string" ? raw[field].trim() : "";
    if (!value) throw new WardrobeValidationError(field, `${label} 값을 입력해 주세요.`);
    if (Array.from(value).length > limit) {
      throw new WardrobeValidationError(field, `${label} 값은 ${limit}자 이내로 입력해 주세요.`);
    }
    payload[field] = value;
  }

  const seasons = raw.seasons === undefined ? [] : raw.seasons;
  if (!Array.isArray(seasons) || seasons.length > 4) {
    throw new WardrobeValidationError("seasons", "계절은 최대 4개까지 선택할 수 있습니다.");
  }
  payload.seasons = Array.from(seasons, (season) => {
    if (typeof season !== "string" || !season.trim() || Array.from(season.trim()).length > 20) {
      throw new WardrobeValidationError("seasons", "계절은 빈 값 없이 각각 20자 이내로 입력해 주세요.");
    }
    return season.trim();
  });
  if (new Set(payload.seasons).size !== payload.seasons.length) {
    throw new WardrobeValidationError("seasons", "계절은 중복 입력할 수 없습니다.");
  }
  return payload;
}

/** Pixel dimensions are checked by the controller while preparing the preview. */
export function validatePhotoFile(file) {
  const extension = typeof file?.name === "string" ? /\.([^.]+)$/.exec(file.name)?.[1].toLowerCase() : "";
  const expectedType = PHOTO_TYPES.get(extension);
  if (!expectedType || typeof file?.type !== "string" || file.type.toLowerCase() !== expectedType) {
    throw new WardrobeValidationError("photo", "JPG, PNG, WEBP 이미지만 업로드할 수 있습니다.");
  }
  if (!Number.isSafeInteger(file.size) || file.size <= 0) {
    throw new WardrobeValidationError("photo", "비어 있지 않은 이미지 파일을 선택해 주세요.");
  }
  if (file.size > MAX_IMAGE_BYTES) {
    throw new WardrobeValidationError("photo", "이미지 크기는 최대 5MB입니다.");
  }
  return file;
}

/** Keep external image URLs intact; refresh only this item's local image URL. */
export function imageSource(item, origin) {
  if (typeof item?.image_url !== "string" || !item.image_url.trim()) return null;
  const raw = item.image_url.trim();
  if (!/^https?:\/\//i.test(raw) && !raw.startsWith("/")) return null;
  try {
    const base = new URL(origin);
    if (!["http:", "https:"].includes(base.protocol) || base.username || base.password) return null;
    const url = new URL(raw, base.origin);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
    if (url.origin === base.origin && url.pathname === `/api/v1/wardrobe/${item.item_id}/image`) {
      if (typeof item.updated_at === "string") url.searchParams.set("v", item.updated_at);
      return url.href;
    }
    return /^https?:\/\//i.test(raw) ? raw : url.href;
  } catch {
    return null;
  }
}

export function itemTitle(item) {
  const color = optionLabel(item?.color, COLOR_LABELS).trim();
  const type = typeof item?.type === "string" ? item.type.trim() : "";
  return [color, type].filter(Boolean).join(" ") || "의류";
}

/** Exact array order matters when deciding whether metadata is already saved. */
export function metadataEqual(payload, item) {
  if (!payload || !item || TEXT_FIELDS.some(([field]) => payload[field] !== item[field])) return false;
  return Array.isArray(payload.seasons) && Array.isArray(item.seasons)
    && payload.seasons.length === item.seasons.length
    && payload.seasons.every((season, index) => season === item.seasons[index]);
}
