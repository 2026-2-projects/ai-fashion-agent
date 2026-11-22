/**
 * Human-readable fallback for a recommended garment whose image cannot be trusted.
 * Uses ONLY already returned recommendation/item fields; never generates facts.
 * External shopping navigation is user-initiated and does not consume SerpApi credits.
 */
import { SLOT_LABELS } from "./recommendation-model.js";

const SLOT_QUERY = Object.freeze({
  top: "상의", bottom: "하의", shoes: "신발", outer: "아우터", accessory: "액세서리",
});
const MAX_QUERY_CHARS = 120;

export function manualSearchQuery(item) {
  const original = typeof item?.name === "string" ? item.name : "";
  // The search phrase is provided as a query string, never as HTML or executable code.
  const name = Array.from(original.trim().replace(/\s+/g, " ")).slice(0, MAX_QUERY_CHARS).join("");
  return [name, SLOT_QUERY[item?.slot] || "의류"].filter(Boolean).join(" ");
}

function node(tag, cls, value) {
  const result = document.createElement(tag);
  if (cls) result.className = cls;
  if (value !== undefined) result.textContent = value;
  return result;
}

/** Only report color/fit terms explicitly present in the recommendation name. */
export function explicitNameDetails(name) {
  const text = typeof name === "string" ? name : "";
  const colors = [
    [/블랙|검정|black/i, "블랙"], [/화이트|흰색|white/i, "화이트"],
    [/아이보리|ivory/i, "아이보리"], [/차콜|charcoal/i, "차콜"],
    [/그레이|gray|grey|회색/i, "그레이"], [/네이비|navy/i, "네이비"],
    [/인디고|indigo/i, "인디고"], [/베이지|beige/i, "베이지"],
    [/브라운|brown|갈색/i, "브라운"], [/카키|khaki/i, "카키"],
    [/그린|green|초록/i, "그린"],
  ].filter(([pattern]) => pattern.test(text)).map(([, label]) => label);
  const fits = [
    [/와이드|wide/i, "와이드"], [/레귤러|regular/i, "레귤러"],
    [/오버사이즈|oversized?/i, "오버사이즈"], [/슬림|slim/i, "슬림"],
    [/테이퍼드|tapered/i, "테이퍼드"], [/스트레이트|straight/i, "스트레이트"],
  ].filter(([pattern]) => pattern.test(text)).map(([, label]) => label);
  return { colors, fits };
}

function explanation(cause, item) {
  if (cause === "mismatch") return "검색된 상품명이 추천 의류와 맞지 않아 사진을 표시하지 않았어요.";
  if (cause === "load_error") return "이미지 링크를 표시할 수 없어 사진 대신 의류 정보를 보여드려요.";
  if (item?.status === "provider_disabled") return "자동 상품 이미지 검색이 설정되지 않아 참고용 사진을 표시할 수 없어요.";
  if (item?.status === "provider_unavailable") return "상품 이미지 검색 서비스에서 응답을 받지 못했어요.";
  if (item?.origin === "wardrobe") return "내 옷장에 이 의류의 사진이 등록되지 않았어요.";
  return "추천 의류에 부합하는 상품 사진을 찾지 못했어요.";
}

function link(href, text) {
  const a = node("a", "cm-search-external", text);
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.referrerPolicy = "no-referrer";
  return a;
}

export function createImageSearchAssist(item, { cause = "not_found", style = "" } = {}) {
  const guide = node("section", "cm-image-search-assist");
  guide.setAttribute("aria-label", `${item.name} 검색 안내`);
  const title = node("p", "cm-image-assist-heading", "사진 대신 추천 의류 정보를 확인해 주세요");
  const notice = node("p", "cm-image-assist-description", explanation(cause, item));
  const details = node("dl", "cm-image-assist-details");
  const attributes = [
    ["의류 이름", item.name],
    ["카테고리", SLOT_LABELS[item.slot] || "의류"],
  ];
  const nameDetails = explicitNameDetails(item.name);
  if (nameDetails.colors.length) attributes.push(["색상 (이름 기준)", nameDetails.colors.join("·")]);
  if (nameDetails.fits.length) attributes.push(["핏 (이름 기준)", nameDetails.fits.join("·")]);
  if (typeof style === "string" && style.trim()) attributes.push(["코디 스타일", style.trim()]);
  for (const [label, value] of attributes) {
    details.append(node("dt", "", label), node("dd", "", value));
  }
  const query = manualSearchQuery(item);
  const searchHeader = node("p", "cm-image-search-label", "직접 검색할 때 사용할 검색어");
  const searchText = node("code", "cm-image-search-query", query);
  const actions = node("div", "cm-image-search-actions");
  const naver = new URL("https://search.shopping.naver.com/search/all");
  naver.searchParams.set("query", query);
  const google = new URL("https://www.google.com/search");
  google.searchParams.set("tbm", "shop");
  google.searchParams.set("q", query);
  actions.append(link(naver.href, "네이버 쇼핑에서 찾기"), link(google.href, "구글 쇼핑에서 찾기"));
  const copy = node("button", "cm-search-copy", "검색어 복사");
  copy.type = "button";
  const copyStatus = node("span", "cm-search-copy-status");
  copyStatus.setAttribute("aria-live", "polite");
  let noticeTimer = null;
  copy.addEventListener("click", async () => {
    if (noticeTimer !== null) clearTimeout(noticeTimer);
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unsupported");
      await navigator.clipboard.writeText(query);
      copyStatus.textContent = "검색어를 복사했어요.";
      noticeTimer = setTimeout(() => { copyStatus.textContent = ""; noticeTimer = null; }, 3000);
    } catch {
      // Keep errors visible; only short-lived success messages auto-dismiss.
      copyStatus.textContent = "복사할 수 없어요. 위 검색어를 직접 선택해 주세요.";
    }
  });
  actions.append(copy);
  guide.append(title, notice, details, searchHeader, searchText, actions, copyStatus);
  return guide;
}
