import { authenticatedRequest, getCurrentUser, refreshSession } from "./auth.js";
import { createLookInteractions } from "./interactions.js";
import { loadRecommendationSnapshot, saveRecommendationSnapshot, clearRecommendationSnapshot } from "./recommendation-snapshot.js";
import { isPlausibleProductImage } from "./product-image-check.js";
import { createImageSearchAssist } from "./image-search-assist.js";
// CLOMORI_IMAGE_SEARCH_GUIDE_V4
import {
  buildRecommendationRequest, validateRecommendation, validateLookImages,
  LOOK_ROLE_LABELS, SLOT_LABELS, TOOL_LABELS, IMAGE_STATUS_LABELS, safeWardrobeImageUrl, recommendationError,
} from "./recommendation-model.js";

export function createRecommendationController({ navigate, onSessionChange, onSessionExpired, isBlocked = () => false }) {
  const $ = (id) => document.getElementById(id);
  const fields = { message: "recommendation-prompt", place: "recommendation-place", date: "recommendation-date", time: "recommendation-time" };
  const form = $("recommendation-form");
  let epoch = 0, active = false, ownerId = null, busy = false, ready = false, operation = "";
  // CLOMORI_RECOMMENDATION_FIXES_V3
  // Session-only, account-scoped snapshot: validated before a reload restores it.
  let memory = null, unverified = null;
  let pendingRecommendation = null;
  const controls = new Map();
  const interactions = createLookInteractions({
    captureContext() {
      const ticket = epoch, expectedId = ownerId;
      if (!active || expectedId === null) return null;
      return { ownerId: expectedId, live: () => live(ticket),
        verify: () => verifyOwner(ticket, expectedId), expire, ownerChanged: changedAccount };
    },
    isBlocked: () => busy || isBlocked() || !ready || !active,
    onBusyChange: () => refreshControls(),
  });

  function live(ticket, expectedId) {
    return active && epoch === ticket && window.location.hash === "#recommendation"
      && (expectedId === undefined || getCurrentUser()?.id === expectedId);
  }
  function locked() { return busy || interactions.isSaving() || isBlocked() || !ready || !active; }
  function message(text = "", kind = "error") {
    $("recommendation-message").textContent = text;
    $("recommendation-message").dataset.kind = kind;
  }
  function element(tag, className = "", text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function readForm() {
    return Object.fromEntries(Object.entries(fields).map(([key, id]) => [key, $(id).value]));
  }
  function fillForm(data) {
    for (const [key, id] of Object.entries(fields)) $(id).value = data?.[key] ?? "";
  }
  function persist() {
    if (ready && ownerId !== null && memory?.ownerId === ownerId && getCurrentUser()?.id === ownerId) {
      saveRecommendationSnapshot(ownerId, memory);
    }
  }
  function rememberDraft() {
    if (active && ready && memory && memory.ownerId === ownerId && getCurrentUser()?.id === ownerId) {
      memory.draft = readForm();
      persist();
    }
  }
  function refreshControls() {
    const disabled = locked();
    $("recommendation-fields").disabled = disabled;
    $("recommendation-submit").disabled = disabled;
    $("recommendation-submit").textContent = busy && operation === "recommend" ? "코디 추천 중…" : "AI 코디 추천받기";
    form.setAttribute("aria-busy", String(busy));
    $("recommendation-loading").hidden = !busy;
    $("recommendation-loading").textContent = operation === "recommend"
      ? "코디를 추천하고 있어요. 잠시 기다려 주세요."
      : operation === "images" ? "의류 이미지를 불러오고 있어요." : "로그인 상태를 확인하고 있어요.";
    $("recommendation-retry").hidden = !active || ready || busy;
    $("recommendation-retry").disabled = busy || isBlocked();
    for (const item of controls.values()) {
      item.toggle.disabled = disabled;
      if (item.retry) item.retry.disabled = disabled;
    }
    for (const button of document.querySelectorAll(".recommendation-example")) button.disabled = disabled;
    interactions.refreshControls();
  }
  function reset() {
    pendingRecommendation?.abort();
    pendingRecommendation = null;
    rememberDraft();
    epoch += 1;
    active = false; ownerId = null; busy = false; ready = false; operation = "";
    interactions.reset();
    const userId = getCurrentUser()?.id;
    if (memory?.ownerId !== userId) memory = null;
    if (unverified?.ownerId !== userId) unverified = null;
    if (memory) {
      for (const record of memory.images.values()) {
        if (record.phase === "loading") {
          record.phase = "error";
          record.error = "이미지 요청 결과를 확인하지 못했어요. 필요하면 다시 확인해 주세요.";
        }
      }
    }
    fillForm();
    $("recommendation-results").hidden = true;
    $("recommendation-grid").replaceChildren();
    $("recommendation-summary").textContent = "";
    $("recommendation-response").hidden = true;
    $("recommendation-response").textContent = "";
    controls.clear();
    message();
    refreshControls();
  }
  function expire() {
    clearRecommendationSnapshot(ownerId);
    memory = null; unverified = null;
    reset();
    onSessionExpired();
  }
  function changedAccount() {
    clearRecommendationSnapshot(ownerId);
    memory = null; unverified = null;
    reset();
    navigate("recommendation", { message: "로그인 계정이 바뀌었어요. 현재 계정에서 새 추천을 요청해 주세요.", kind: "info" });
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
  function acceptUnverified() {
    if (!unverified || unverified.ownerId !== ownerId) return false;
    const pending = unverified;
    if (pending.kind === "recommend") {
      interactions.reset();
      memory = { ownerId, draft: pending.draft, result: pending.result, images: new Map() };
    } else if (memory?.result?.recommendation_id === pending.recommendationId) {
      const record = memory.images.get(pending.lookId);
      if (record) {
        record.data = pending.data; record.phase = "ready"; record.error = ""; record.expanded = true;
      }
    }
    unverified = null;
    persist();
    return true;
  }
  function imageRecord(lookId) {
    let record = memory.images.get(lookId);
    if (!record) {
      record = { phase: "idle", expanded: false, data: null, error: "" };
      memory.images.set(lookId, record);
    }
    return record;
  }
  function renderImage(item, lookId, index, style) {
    const figure = element("figure", "look-image-card");
    const frame = element("div", "look-image-frame");
    const label = element("p", "look-image-placeholder", item.status === "not_found" && item.origin === "wardrobe"
      ? "등록된 사진 없음" : IMAGE_STATUS_LABELS[item.status]);
    frame.append(label);
    const mismatched = item.status === "found" && item.origin === "google_shopping"
      && !isPlausibleProductImage(item.name, item.image.title, item.slot);
    if (mismatched) {
      frame.classList.add("look-image-rejected");
      label.textContent = "상품명이 추천 의류와 달라 이미지를 숨겼어요.";
    }
    // No large empty image frame when search is unavailable or relevance validation fails.
    if (item.status !== "found" || mismatched) figure.classList.add("cm-image-absent");
    if (item.status === "found" && !mismatched) {
      const img = element("img");
      img.alt = item.image.title || item.name;
      img.loading = "lazy";
      img.decoding = "async";
      img.referrerPolicy = "no-referrer";
      const ticket = epoch, expectedId = ownerId;
      label.hidden = true;
      img.addEventListener("error", () => {
        if (!live(ticket, expectedId)) return;
        img.hidden = true;
        label.hidden = false;
        label.textContent = "사진을 표시하지 못했어요.";
        figure.classList.add("cm-image-absent");
        if (!caption.querySelector(".cm-image-search-assist")) {
          caption.append(createImageSearchAssist(item, { cause: "load_error", style }));
        }
        // A failed image URL never triggers a new product-search request.
      });
      img.src = item.image.url;
      frame.append(img);
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
        link.href = item.image.source_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.referrerPolicy = "no-referrer";
        caption.append(link);
      } else if (item.image.source_name) caption.append(element("p", "", item.image.source_name));
    }
    if (item.status !== "found" || mismatched) {
      caption.append(createImageSearchAssist(item, {
        cause: mismatched ? "mismatch" : "not_found", style,
      }));
    }
    figure.dataset.slot = item.slot;
    figure.dataset.lookId = String(lookId);
    figure.dataset.index = String(index);
    figure.append(frame, caption);
    return figure;
  }
  function renderResults() {
    controls.clear();
    interactions.beginRender();
    const grid = $("recommendation-grid");
    grid.replaceChildren();
    if (!ready || !memory?.result || memory.ownerId !== ownerId) {
      $("recommendation-results").hidden = true;
      $("recommendation-response").hidden = true;
      return;
    }
    const result = memory.result;
    $("recommendation-results").hidden = false;
    $("recommendation-summary").textContent = result.context_summary;
    $("recommendation-response").textContent = "조회한 정보: " + result.called_tools.map(name => TOOL_LABELS[name]).join(" · ");
    $("recommendation-response").hidden = false;
    for (const look of result.looks) {
      const card = element("article", "look-card");
      card.dataset.lookId = String(look.look_id);
      card.dataset.status = look.status;
      const header = element("div", "look-card-header");
      header.append(element("h3", "look-number", "LOOK " + look.look_id),
        element("p", "look-role", LOOK_ROLE_LABELS[look.role]));
      card.append(header, element("p", "look-style", look.style || "추천 가능한 조합이 없어요"));
      /* CLOMORI V2: visual preview from validated, first-party wardrobe images only. */
      card.dataset.role = look.role;
      if (look.status === "available") {
        const preview = element("div", "cm-look-visual");
        const isWardrobe = look.role === "wardrobe_best" || look.role === "wardrobe_alternative";
        if (isWardrobe) {
          for (const item of look.items) {
            const url = safeWardrobeImageUrl(item.image_url, item.item_id);
            if (!url) continue;
            const image = document.createElement("img");
            image.src = url;
            image.alt = item.name;
            image.loading = look.role === "wardrobe_best" ? "eager" : "lazy";
            image.addEventListener("error", () => {
              image.hidden = true;
              preview.dataset.missing = "true";
            });
            preview.append(image);
          }
        }
        // LOOK 1–3 are text-first until an actual external image has been resolved.
        // Do not generate a fake shirt/trousers illustration.
        if (isWardrobe) {
          if (preview.querySelector("img")) {
            preview.append(element("span", "cm-visual-caption", "MY WARDROBE"));
          } else {
            preview.append(element("p", "cm-wardrobe-empty", "등록된 옷장 사진이 없어요."));
          }
          card.insertBefore(preview, card.firstChild);
        }
      }
      if (look.status === "available") {
        const items = element("ul", "look-items");
        for (const item of look.items) {
          const row = element("li", "look-item");
          row.append(element("span", "look-slot", SLOT_LABELS[item.slot]), element("span", "look-item-name", item.name));
          items.append(row);
        }
        card.append(items);
      }
      card.append(element("p", "look-reason", look.reason));
      if (look.status === "available") {
        const record = imageRecord(look.look_id);
        // When the wardrobe photo is already visible in this card, avoid the redundant Image View control.
        const wardrobePreviewVisible = look.look_id >= 4
          && look.items.some(item => Boolean(safeWardrobeImageUrl(item.image_url, item.item_id)));
        if (!wardrobePreviewVisible) {
        const actions = element("div", "look-actions");
        const toggle = element("button", "button secondary-button", record.phase === "loading" ? "이미지 확인 중…"
          : record.data ? (record.expanded ? "이미지 접기" : "이미지 보기")
          : record.phase === "error" ? "이미지 다시 확인" : "이미지 보기");
        toggle.type = "button";
        toggle.dataset.action = "images";
        toggle.dataset.lookId = String(look.look_id);
        const panelId = "look-images-" + look.look_id;
        toggle.setAttribute("aria-controls", panelId);
        toggle.setAttribute("aria-expanded", String(record.expanded));
        toggle.addEventListener("click", () => { void showImages(look.look_id, false); });
        actions.append(toggle);
        // Do not present a second "retry" CTA for cached not-found/mismatched results.
        // The primary image button still retries genuine fetch failures with no cached data.
        const retry = null;
        card.append(actions, interactions.mount(result.recommendation_id, look));
        const status = element("p", "look-image-status");
        status.setAttribute("role", "status");
        status.setAttribute("aria-live", "polite");
        const rejectedImages = record.data?.items.some(item => item.status === "found"
          && item.origin === "google_shopping" && !isPlausibleProductImage(item.name, item.image.title, item.slot));
        status.textContent = record.error || (record.phase === "loading" ? "의류 이미지를 확인하고 있어요."
          : rejectedImages ? "일치하지 않는 이미지 대신 추천 의류명과 직접 검색 링크를 제공해요."
          : record.data?.resolution_status === "partial" ? "일부 상품의 사진을 찾지 못했어요. 의류별 검색어와 직접 검색 링크를 확인해 주세요." : "");
        card.append(status);
        const panel = element("div", "look-image-grid");
        panel.id = panelId;
        panel.hidden = !record.expanded || !record.data;
        if (record.expanded && record.data) {
          record.data.items.forEach((item, index) => panel.append(renderImage(item, look.look_id, index, look.style)));
        }
        card.append(panel);
        controls.set(look.look_id, { toggle, retry });
        } else {
          card.append(interactions.mount(result.recommendation_id, look));
        }
      }
      grid.append(card);
    }
    refreshControls();
  }

  async function open(notice) {
    reset();
    active = true;
    const ticket = epoch, beforeId = getCurrentUser()?.id;
    busy = true; operation = "load";
    refreshControls();
    try {
      const user = await refreshSession();
      if (!live(ticket)) return;
      onSessionChange();
      if (!user) { expire(); return; }
      if (beforeId !== undefined && user.id !== beforeId) { changedAccount(); return; }
      ownerId = user.id;
      if (memory?.ownerId !== user.id) memory = { ownerId, draft: null, result: null, images: new Map() };
      // Rehydrate only AFTER /auth/me has independently verified the logged-in account.
      if (!memory.result) memory = loadRecommendationSnapshot(user.id) || memory;
      if (unverified?.ownerId !== user.id) unverified = null;
      const recovered = acceptUnverified();
      fillForm(memory.draft);
      ready = true;
      message(notice?.message || (recovered ? "로그인 상태를 확인했어요. 이미 받은 결과를 표시했어요." : ""), notice?.kind || "info");
    } catch (error) {
      if (!requestIsCurrent(ticket, beforeId)) return;
      if (error.status === 401) { expire(); return; }
      ready = false;
      message(recommendationError(error) + " ‘다시 확인’을 눌러 로그인 상태를 확인해 주세요.");
    } finally {
      if (live(ticket)) {
        busy = false; operation = "";
        renderResults(); refreshControls();
      }
    }
    if (live(ticket) && ready && memory?.result) {
      await interactions.load(memory.result.recommendation_id, memory.result.looks);
    }
  }

  async function generate(event) {
    event.preventDefault();
    if (locked() || ownerId === null) return;
    let payload;
    const draft = readForm();
    try { payload = buildRecommendationRequest(draft); }
    catch (error) {
      message(error.message);
      if (fields[error.field]) $(fields[error.field]).focus();
      return;
    }
    const ticket = epoch, expectedId = ownerId;
    memory.draft = draft;
    busy = true; operation = "recommend";
    message();
    refreshControls();
    const controller = new AbortController();
    pendingRecommendation = controller;
    let generated = false;
    try {
      if (!await verifyOwner(ticket, expectedId)) return;
      const result = validateRecommendation(await authenticatedRequest("/agent/recommend", {
        method: "POST", body: payload, timeoutMs: 90000, signal: controller.signal,
      }));
      if (!requestIsCurrent(ticket, expectedId)) return;
      unverified = { kind: "recommend", ownerId: expectedId, result, draft };
      if (!await verifyOwner(ticket, expectedId)) return;
      acceptUnverified();
      generated = true;
      message("5개 LOOK의 추천 결과를 확인해 주세요.", "success");
    } catch (error) {
      if (!requestIsCurrent(ticket, expectedId)) return;
      if (error.status === 401) { expire(); return; }
      if (unverified?.kind === "recommend" && unverified.ownerId === expectedId) {
        ready = false;
        message("추천 결과는 받았지만 로그인 상태를 다시 확인하지 못했어요. ‘다시 확인’을 누르면 받은 결과를 이어서 확인할 수 있어요.", "info");
      } else {
        message(recommendationError(error) + (!error.status
          ? " 요청을 자동으로 반복하지 않았어요. 다시 요청하면 새 추천을 만들어요." : ""));
      }
    } finally {
      if (pendingRecommendation === controller) pendingRecommendation = null;
      if (live(ticket)) {
        busy = false; operation = "";
        renderResults(); refreshControls();
        if (generated) $("recommendation-results-heading").focus({ preventScroll: false });
      }
    }
    if (generated && live(ticket) && ready && memory?.result) {
      await interactions.load(memory.result.recommendation_id, memory.result.looks);
    }
  }

  async function showImages(lookId, force) {
    if (locked() || !memory?.result || ownerId === null) return;
    const look = memory.result.looks.find(item => item.look_id === lookId);
    if (!look || look.status !== "available") return;
    const record = imageRecord(lookId);
    if (record.data && !force) {
      record.expanded = !record.expanded;
      persist();
      renderResults();
      controls.get(lookId)?.toggle.focus({ preventScroll: true });
      return;
    }
    const ticket = epoch, expectedId = ownerId, recommendationId = memory.result.recommendation_id;
    busy = true; operation = "images";
    record.phase = "loading"; record.error = ""; record.expanded = true;
    message();
    renderResults(); refreshControls();
    try {
      if (!await verifyOwner(ticket, expectedId)) return;
      const data = validateLookImages(await authenticatedRequest(
        "/recommendations/" + recommendationId + "/looks/" + lookId + "/images", { timeoutMs: 45000 },
      ), recommendationId, look);
      if (!requestIsCurrent(ticket, expectedId)) return;
      unverified = { kind: "images", ownerId: expectedId, recommendationId, lookId, data };
      if (!await verifyOwner(ticket, expectedId)) return;
      acceptUnverified();
    } catch (error) {
      if (!requestIsCurrent(ticket, expectedId)) return;
      if (error.status === 401) { expire(); return; }
      if (unverified?.kind === "images" && unverified.ownerId === expectedId) {
        ready = false;
        record.phase = "verify";
        message("이미지 정보는 받았지만 로그인 상태를 다시 확인하지 못했어요. ‘다시 확인’을 눌러 이어서 확인해 주세요.", "info");
      } else {
        record.phase = "error";
        record.error = recommendationError(error, "images");
      }
    } finally {
      if (live(ticket)) {
        busy = false; operation = "";
        renderResults(); refreshControls();
        if (ready) controls.get(lookId)?.toggle.focus({ preventScroll: true });
      }
    }
  }

  form.addEventListener("submit", (event) => { void generate(event); });
  form.addEventListener("input", rememberDraft);
  $("recommendation-retry").addEventListener("click", () => {
    if (!busy && !isBlocked()) void open();
  });
  for (const button of document.querySelectorAll(".recommendation-example")) {
    button.addEventListener("click", () => {
      if (locked()) return;
      $("recommendation-prompt").value = button.dataset.prompt || "";
      if (button.dataset.context) $("recommendation-options").open = true;
      rememberDraft();
      $("recommendation-prompt").focus();
    });
  }
  reset();
  return { open, reset, refreshControls, isSaving() { return busy || interactions.isSaving(); } };
}
