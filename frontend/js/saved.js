import { authenticatedRequest, getCurrentUser, refreshSession } from "./auth.js";
import { createLookInteractions } from "./interactions.js";
import { isPlausibleProductImage } from "./product-image-check.js";
import { createImageSearchAssist } from "./image-search-assist.js";
import { loadRecommendationSnapshot } from "./recommendation-snapshot.js";
// CLOMORI_IMAGE_LAYOUT_PARITY_V5
// CLOMORI_IMAGE_SEARCH_GUIDE_V4
// CLOMORI_RECOMMENDATION_FIXES_V3
import { validateSavedOutfits, interactionError } from "./interaction-model.js";
import { LOOK_ROLE_LABELS, SLOT_LABELS, IMAGE_STATUS_LABELS, validateLookImages, recommendationError } from "./recommendation-model.js";

export function createSavedController({ navigate, onSessionChange, onSessionExpired, isBlocked = () => false }) {
  const $ = (id) => document.getElementById(id);
  let epoch = 0, active = false, ownerId = null, busy = false, ready = false, rows = [];
  // Images are memory-only and tied to one account; the saved list always comes from the server.
  let imageMemory = null;
  const imageControls = new Map();
  const interactions = createLookInteractions({
    captureContext() {
      const ticket = epoch, expectedId = ownerId;
      if (!active || expectedId === null) return null;
      return { ownerId: expectedId, live: () => live(ticket), verify: () => verifyOwner(ticket, expectedId), expire, ownerChanged: changedAccount };
    },
    isBlocked: () => busy || isBlocked() || !ready || !active,
    onBusyChange: () => refreshControls(),
    onChange(states) {
      const removed = rows.filter(row => states.some(state =>
        state.recommendation_id.toLowerCase() === row.recommendation_id
        && state.look_id === row.look_id && !state.saved));
      if (!removed.length) return;
      const ids = new Set(removed.map(row => row.id));
      rows = rows.filter(row => !ids.has(row.id));
      for (const id of ids) imageMemory?.entries.delete(id);
      message("서버 상태에 맞게 저장 목록을 갱신했어요.", "success");
      render();
      $("saved").querySelector("h1")?.focus({ preventScroll: true });
    },
  });
  function live(ticket, expectedId) {
    return active && epoch === ticket && window.location.hash === "#saved"
      && (expectedId === undefined || getCurrentUser()?.id === expectedId);
  }
  function locked() { return busy || interactions.isSaving() || isBlocked() || !ready || !active; }
  function message(text = "", kind = "error") {
    $("saved-message").textContent = text;
    $("saved-message").dataset.kind = kind;
  }
  function element(tag, className = "", text) {
    const node = document.createElement(tag); node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function refreshControls() {
    const disabled = locked();
    $("saved-refresh").disabled = busy || interactions.isSaving() || isBlocked() || !active;
    $("saved-loading").hidden = !busy;
    $("saved-retry").hidden = !active || ready || busy;
    $("saved-retry").disabled = busy || interactions.isSaving() || isBlocked();
    $("saved-grid").setAttribute("aria-busy", String(busy || interactions.isSaving()));
    for (const controls of imageControls.values()) for (const control of controls) control.disabled = disabled;
    interactions.refreshControls();
  }
  function reset() {
    epoch += 1;
    active = false; ownerId = null; busy = false; ready = false; rows = [];
    interactions.reset();
    if (imageMemory?.ownerId !== getCurrentUser()?.id) imageMemory = null;
    if (imageMemory) {
      for (const record of imageMemory.entries.values()) {
        if (record.phase === "loading") {
          record.phase = "error"; record.error = "이미지 요청 결과를 확인하지 못했어요. 필요하면 다시 확인해 주세요.";
        }
      }
    }
    imageControls.clear();
    $("saved-grid").replaceChildren();
    $("saved-empty").hidden = true;
    $("saved-count").textContent = "";
    message(); refreshControls();
  }
  function expire() {
    imageMemory = null; reset(); onSessionExpired();
  }
  function changedAccount() {
    imageMemory = null; reset();
    navigate("saved", { message: "로그인 계정이 바뀌었어요. 현재 계정의 저장 목록을 다시 확인해 주세요.", kind: "info" });
  }
  function requestIsCurrent(ticket, expectedId) {
    if (!live(ticket)) return false;
    const currentId = getCurrentUser()?.id;
    if (expectedId !== undefined && currentId !== undefined && currentId !== expectedId) {
      changedAccount(); return false;
    }
    return true;
  }
  async function verifyOwner(ticket, expectedId) {
    const user = await refreshSession();
    if (!live(ticket)) return false;
    onSessionChange();
    if (!user) { expire(); return false; }
    if (user.id !== expectedId) { changedAccount(); return false; }
    return true;
  }
  function imageRecord(row) {
    let record = imageMemory.entries.get(row.id);
    if (!record || record.recommendationId !== row.recommendation_id || record.lookId !== row.look_id) {
      record = { recommendationId: row.recommendation_id, lookId: row.look_id,
        phase: "idle", data: null, pending: null, expanded: false, error: "" };
      imageMemory.entries.set(row.id, record);
    }
    // Preserve the exact resolved images already shown on the recommendation screen.
    // The stored recommendation snapshot belongs to this logged-in user and is
    // validated again against the saved outfit before it is displayed.
    if (!record.data && record.phase === "idle" && Number.isSafeInteger(ownerId)) {
      const snapshot = loadRecommendationSnapshot(ownerId);
      if (snapshot?.result?.recommendation_id?.toLowerCase() === row.recommendation_id?.toLowerCase()) {
        const existing = snapshot.images.get(row.look_id);
        if (existing?.phase === "ready" && existing.data && row.look) {
          try {
            record.data = validateLookImages(existing.data, row.recommendation_id, row.look);
            record.phase = "ready";
            record.error = "";
          } catch {
            // If the saved outfit changed, ignore the stale snapshot and fetch on demand.
          }
        }
      }
    }
    return record;
  }
  function renderImage(item, style) {
    const figure = element("figure", "look-image-card"), frame = element("div", "look-image-frame");
    const placeholder = element("p", "look-image-placeholder", item.status === "not_found" && item.origin === "wardrobe"
      ? "등록된 사진 없음" : IMAGE_STATUS_LABELS[item.status]);
    frame.append(placeholder);
    const mismatched = item.status === "found" && item.origin === "google_shopping"
      && !isPlausibleProductImage(item.name, item.image.title, item.slot);
    if (mismatched) {
      frame.classList.add("look-image-rejected");
      placeholder.textContent = "상품명이 추천 의류와 달라 이미지를 숨겼어요.";
    }
    if (item.status !== "found" || mismatched) figure.classList.add("cm-image-absent");
    if (item.status === "found" && !mismatched) {
      const image = element("img"), ticket = epoch, expectedId = ownerId;
      image.alt = item.image.title || item.name; image.loading = "lazy"; image.decoding = "async";
      image.referrerPolicy = "no-referrer"; placeholder.hidden = true;
      image.addEventListener("error", () => {
        if (!live(ticket, expectedId)) return;
        image.hidden = true; placeholder.hidden = false; placeholder.textContent = "사진을 표시하지 못했어요.";
        figure.classList.add("cm-image-absent");
        if (!caption.querySelector(".cm-image-search-assist")) {
          caption.append(createImageSearchAssist(item, { cause: "load_error", style }));
        }
      });
      image.src = item.image.url; frame.append(image);
    }
    const caption = element("figcaption", "look-image-meta");
    caption.append(element("p", "", SLOT_LABELS[item.slot]), element("p", "", item.name));
    if (mismatched) {
      caption.append(element("p", "", "상품명 불일치 · 이 이미지는 표시하지 않습니다."));
    } else if (item.image) {
      caption.append(element("p", "", item.origin === "wardrobe" ? "내 옷장 사진" : "참고용 상품 이미지"));
      if (item.image.title !== item.name) caption.append(element("p", "", item.image.title));
      if (item.image.source_url) {
        const link = element("a", "look-image-source", item.image.source_name || "상품 출처 보기");
        link.href = item.image.source_url; link.target = "_blank";
        link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer"; caption.append(link);
      } else if (item.image.source_name) caption.append(element("p", "", item.image.source_name));
    }
    if (item.status !== "found" || mismatched) {
      caption.append(createImageSearchAssist(item, {cause: mismatched ? "mismatch" : "not_found", style}));
    }
    figure.append(frame, caption); return figure;
  }
  function render() {
    interactions.beginRender(); imageControls.clear();
    const grid = $("saved-grid"); grid.replaceChildren();
    $("saved-count").textContent = ready ? "저장한 코디 " + rows.length + "개" : "";
    $("saved-empty").hidden = !ready || rows.length !== 0;
    if (!ready) { refreshControls(); return; }
    for (const row of rows) {
      const card = element("article", "look-card");
      card.dataset.savedId = String(row.id);
      card.dataset.lookId = row.look_id === null ? "" : String(row.look_id);
      card.dataset.recommendationId = row.recommendation_id || "";
      const header = element("div", "look-card-header");
      header.append(element("h2", "look-number", row.look ? "LOOK " + row.look_id : "저장한 코디"));
      if (row.look) header.append(element("p", "look-role", LOOK_ROLE_LABELS[row.look.role]));
      card.append(header, element("p", "look-style", row.title));
      const date = row.created_at ? new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium" }).format(new Date(row.created_at)) : "날짜 정보 없음";
      card.append(element("p", "saved-card-meta", "저장일 · " + date));
      if (row.notice) card.append(element("p", "saved-card-note", row.notice));
      if (row.look) {
        const list = element("ul", "look-items");
        for (const item of row.look.items) {
          const line = element("li", "look-item");
          line.append(element("span", "look-slot", SLOT_LABELS[item.slot]), element("span", "look-item-name", item.name));
          list.append(line);
        }
        card.append(list, element("p", "look-reason", row.look.reason));
      }
      if (row.manageable) {
        const record = imageRecord(row), panelId = "saved-images-" + row.id;
        const actions = element("div", "look-actions");
        const toggle = element("button", "button secondary-button", record.phase === "loading" ? "이미지 확인 중…"
          : record.data ? record.expanded ? "이미지 접기" : "이미지 보기"
          : record.phase === "error" ? "이미지 다시 확인" : "이미지 보기");
        toggle.type = "button"; toggle.dataset.action = "images";
        toggle.dataset.savedId = String(row.id); toggle.dataset.lookId = String(row.look_id);
        toggle.setAttribute("aria-controls", panelId); toggle.setAttribute("aria-expanded", String(record.expanded));
        toggle.addEventListener("click", () => { void showImages(row.id, false); });
        const buttons = [toggle]; actions.append(toggle);
        // Partial results are cached server-side. Manual search links are provided instead of a misleading repeat button.
        card.append(actions, interactions.mount(row.recommendation_id, row.look, { savedOnly: true }));
        const status = element("p", "look-image-status", record.error || (record.phase === "loading" ? "의류 이미지를 확인하고 있어요."
          : record.data?.resolution_status === "partial" ? "일부 이미지가 없어요. 저장한 코디 내용은 계속 확인할 수 있어요." : ""));
        status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
        const panel = element("div", "look-image-grid"); panel.id = panelId;
        panel.hidden = !record.expanded || !record.data;
        if (record.expanded && record.data) for (const item of record.data.items) panel.append(renderImage(item, row.look?.style || ""));
        if (record.expanded && record.data && row.look) {
          const slots = row.look.items.map(item => SLOT_LABELS[item.slot]).join(" · ");
          card.append(element("p", "cm-image-count-note",
            `원본 추천에 포함된 의류 ${row.look.items.length}개 · ${slots}`));
        }
        card.append(status, panel); imageControls.set(row.id, buttons);
      }
      grid.append(card);
    }
    refreshControls();
  }
  async function open(notice) {
    reset(); active = true; busy = true;
    const ticket = epoch, beforeId = getCurrentUser()?.id;
    let expectedId = beforeId;
    $("saved-loading").textContent = "저장한 코디를 불러오고 있어요."; refreshControls();
    try {
      const user = await refreshSession();
      if (!live(ticket)) return;
      onSessionChange();
      if (!user) { expire(); return; }
      if (beforeId !== undefined && user.id !== beforeId) { changedAccount(); return; }
      ownerId = user.id;
      expectedId = user.id;
      if (imageMemory?.ownerId !== ownerId) imageMemory = { ownerId, entries: new Map() };
      const response = validateSavedOutfits(await authenticatedRequest("/saved-outfits"));
      if (!requestIsCurrent(ticket, expectedId) || !await verifyOwner(ticket, expectedId)) return;
      rows = response; ready = true;
      const retained = new Set(rows.filter(row => row.manageable).map(row => row.id));
      for (const id of imageMemory.entries.keys()) if (!retained.has(id)) imageMemory.entries.delete(id);
      for (const row of rows.filter(row => row.manageable)) {
        const record = imageRecord(row);
        if (record.data) {
          try {
            record.data = validateLookImages(record.data, row.recommendation_id, row.look);
          } catch {
            record.data = null; record.expanded = false; record.phase = "error";
            record.error = "저장한 코디 내용과 이미지 정보가 달라요. 필요하면 이미지를 다시 확인해 주세요.";
          }
        }
        if (record.pending) {
          try {
            record.data = validateLookImages(record.pending, row.recommendation_id, row.look);
            record.phase = "ready"; record.error = ""; record.expanded = true;
          } catch {
            record.data = null; record.expanded = false;
            record.phase = "error"; record.error = "이전에 받은 이미지 정보를 확인하지 못했어요.";
          }
          record.pending = null;
        }
      }
      message(notice?.message || "", notice?.kind || "info");
    } catch (error) {
      if (!requestIsCurrent(ticket, expectedId)) return;
      if (error.status === 401) { expire(); return; }
      ready = false; message(interactionError(error) + " ‘다시 확인’을 눌러 목록을 불러와 주세요.");
    } finally {
      if (live(ticket)) { busy = false; render(); refreshControls(); }
    }
  }
  async function showImages(savedId, force) {
    if (locked()) return;
    const row = rows.find(item => item.id === savedId && item.manageable);
    if (!row) return;
    const record = imageRecord(row);
    if (record.data && !force) {
      record.expanded = !record.expanded; render();
      imageControls.get(savedId)?.[0].focus({ preventScroll: true }); return;
    }
    const ticket = epoch, expectedId = ownerId;
    busy = true; record.phase = "loading"; record.error = ""; record.expanded = true;
    $("saved-loading").textContent = "의류 이미지를 불러오고 있어요."; message(); render(); refreshControls();
    try {
      if (!await verifyOwner(ticket, expectedId)) return;
      const data = validateLookImages(await authenticatedRequest(
        "/recommendations/" + row.recommendation_id + "/looks/" + row.look_id + "/images", { timeoutMs: 45000 },
      ), row.recommendation_id, row.look);
      if (!requestIsCurrent(ticket, expectedId)) return;
      record.pending = data;
      if (!await verifyOwner(ticket, expectedId)) return;
      record.data = data; record.pending = null; record.phase = "ready";
    } catch (error) {
      if (!requestIsCurrent(ticket, expectedId)) return;
      if (error.status === 401) { expire(); return; }
      if (record.pending) {
        ready = false; record.phase = "verify";
        message("이미지는 받았지만 로그인 상태를 확인하지 못했어요. ‘다시 확인’을 누르면 받은 이미지 정보를 이어서 확인할 수 있어요.", "info");
      } else {
        record.phase = "error"; record.error = recommendationError(error, "images");
      }
    } finally {
      if (live(ticket)) {
        busy = false; render(); refreshControls();
        if (ready) imageControls.get(savedId)?.[0].focus({ preventScroll: true });
      }
    }
  }
  for (const id of ["saved-refresh", "saved-retry"]) $(id).addEventListener("click", () => {
    if (!busy && !interactions.isSaving() && !isBlocked()) void open();
  });
  reset();
  return { open, reset, refreshControls, isSaving: () => busy || interactions.isSaving() };
}
