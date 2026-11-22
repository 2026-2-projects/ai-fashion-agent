import { authenticatedRequest, getCurrentUser, refreshSession } from "./auth.js";
import {
  CATEGORY_OPTIONS, SEASON_OPTIONS, MAX_IMAGE_PIXELS,
  normalizeCategory, categoryLabel, fitLabel, seasonLabel,
  validateItem, validateWardrobeInput, validatePhotoFile, imageSource, itemTitle, metadataEqual,
} from "./wardrobe-model.js";

export function createWardrobeController({ navigate, replaceRoute, onSessionChange, onSessionExpired }) {
  const $ = (id) => document.getElementById(id);
  const form = $("wardrobe-form");
  const fields = $("wardrobe-fields");
  const photo = $("wardrobe-photo");
  const preview = $("wardrobe-preview");
  let epoch = 0, photoEpoch = 0;
  let activeRoute = null, ownerId = null, currentItem = null;
  let items = [], filter = "all";
  let busy = false, ready = false, uncertainCreate = false;
  let selectedFile = null, previewUrl = null, photoReady = true, photoError = "";
  let photoRetry = false;

  const messageId = () => activeRoute === "closet" ? "closet-message" : "wardrobe-message";
  function message(text = "", kind = "error") {
    const target = $(messageId());
    target.textContent = text;
    target.dataset.kind = kind;
  }
  function live(ticket, expectedId) {
    return ticket === epoch && window.location.hash === "#" + activeRoute
      && (expectedId === undefined || getCurrentUser()?.id === expectedId);
  }
  function buttons() {
    fields.disabled = !ready || busy;
    form.setAttribute("aria-busy", String(busy || !ready));
    $("wardrobe-save").disabled = busy || !ready || !photoReady || !!photoError || uncertainCreate;
    $("wardrobe-save").textContent = photoRetry ? "사진 다시 올리기" : "저장";
    $("wardrobe-clear-file").hidden = !selectedFile;
    $("wardrobe-delete-photo").hidden = !currentItem?.image_url;
    $("wardrobe-delete-photo").disabled = busy || !!selectedFile;
    $("closet-retry").disabled = busy;
    $("wardrobe-retry").disabled = busy;
    $("closet-list").querySelectorAll("button").forEach((button) => { button.disabled = busy; });
    $("closet-filters").querySelectorAll("button").forEach((button) => { button.disabled = busy; });
  }
  function releasePreview() {
    photoEpoch += 1;
    preview.onload = null;
    preview.onerror = null;
    preview.removeAttribute("src");
    preview.hidden = true;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
  function storedPreview() {
    releasePreview();
    const placeholder = $("wardrobe-photo-placeholder");
    placeholder.hidden = false;
    placeholder.textContent = "사진을 선택하면 여기에 표시돼요.";
    const src = currentItem && imageSource(currentItem, window.location.origin);
    if (!src) return;
    const ticket = photoEpoch;
    preview.alt = itemTitle(currentItem);
    preview.referrerPolicy = "no-referrer";
    preview.onerror = () => {
      if (ticket !== photoEpoch) return;
      preview.hidden = true;
      placeholder.hidden = false;
      placeholder.textContent = "등록된 사진을 불러오지 못했어요.";
    };
    preview.onload = () => {
      if (ticket !== photoEpoch) return;
      preview.hidden = false;
      placeholder.hidden = true;
    };
    preview.src = src;
  }
  function clearFile() {
    selectedFile = null;
    photo.value = "";
    photoReady = true;
    photoError = "";
    photoRetry = false;
    $("wardrobe-file-info").textContent = "";
    storedPreview();
    buttons();
  }
  function reset() {
    epoch += 1;
    activeRoute = null;
    ownerId = null;
    currentItem = null;
    items = [];
    filter = "all";
    busy = false;
    ready = false;
    uncertainCreate = false;
    form.reset();
    for (const id of ["wardrobe-category", "wardrobe-fit"]) {
      $(id).querySelectorAll("option[data-existing]").forEach((node) => node.remove());
      $(id).value = "";
    }
    $("wardrobe-seasons-options").replaceChildren();
    $("closet-list").replaceChildren();
    $("closet-filters").replaceChildren();
    $("closet-empty").hidden = true;
    $("closet-count").textContent = "";
    for (const id of ["closet-message", "wardrobe-message"]) $(id).textContent = "";
    $("closet-retry").hidden = true;
    $("wardrobe-retry").hidden = true;
    clearFile();
    buttons();
    form.setAttribute("aria-busy", "false");
  }
  function expire() {
    reset();
    onSessionExpired();
  }
  function changedAccount() {
    reset();
    navigate("closet", {
      message: "로그인 계정이 바뀌었어요. 현재 계정의 옷장을 다시 확인해 주세요.",
      kind: "info",
    });
  }
  async function verifyOwner(ticket, expectedId) {
    const user = await refreshSession();
    if (!live(ticket)) return false;
    onSessionChange();
    if (!user) { expire(); return false; }
    if (user.id !== expectedId) { changedAccount(); return false; }
    return true;
  }
  function selectExisting(id, value) {
    const select = $(id);
    select.querySelectorAll("option[data-existing]").forEach((node) => node.remove());
    if (value && ![...select.options].some((option) => option.value === value)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value + " (기존)";
      option.dataset.existing = "true";
      select.append(option);
    }
    select.value = value || "";
  }
  function fillEditor(item) {
    selectExisting("wardrobe-category", item?.category || "");
    selectExisting("wardrobe-fit", item?.fit || "");
    $("wardrobe-type").value = item?.type || "";
    $("wardrobe-color").value = item?.color || "";
    const seasons = item?.seasons || [];
    const options = [...SEASON_OPTIONS];
    for (const value of seasons) {
      if (!options.some(([known]) => known === value)) options.push([value, value + " (기존)"]);
    }
    const container = $("wardrobe-seasons-options");
    container.replaceChildren();
    for (const [value, label] of options) {
      const wrapper = document.createElement("label");
      wrapper.className = "choice";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "seasons";
      input.value = value;
      input.checked = seasons.includes(value);
      const text = document.createElement("span");
      text.className = "choice-label";
      text.textContent = label;
      wrapper.append(input, text);
      container.append(wrapper);
    }
    $("wardrobe-title").textContent = item ? "옷 수정하기" : "옷 추가하기";
    storedPreview();
  }
  function payload() {
    const checked = [...$("wardrobe-seasons-options").querySelectorAll("input:checked")].map((input) => input.value);
    const original = currentItem?.seasons || [];
    return validateWardrobeInput({
      category: $("wardrobe-category").value,
      type: $("wardrobe-type").value,
      color: $("wardrobe-color").value,
      fit: $("wardrobe-fit").value,
      seasons: [...original.filter((value) => checked.includes(value)), ...checked.filter((value) => !original.includes(value))],
    });
  }
  function showValidation(error) {
    const ids = {
      category: "wardrobe-category", type: "wardrobe-type", color: "wardrobe-color",
      fit: "wardrobe-fit", seasons: "wardrobe-seasons-options", photo: "wardrobe-photo",
    };
    message(error.message);
    const target = $(ids[error.field] || "wardrobe-type");
    (target?.querySelector("input") || target)?.focus();
  }
  function renderFilters() {
    const container = $("closet-filters");
    container.replaceChildren();
    const options = [["all", "전체"], ...CATEGORY_OPTIONS];
    if (items.some((item) => normalizeCategory(item.category) === "other")) options.push(["other", "기타 분류"]);
    if (!options.some(([value]) => value === filter)) filter = "all";
    for (const [value, label] of options) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "category-filter";
      button.dataset.category = value;
      const count = value === "all" ? items.length : items.filter((item) => normalizeCategory(item.category) === value).length;
      button.textContent = label + " " + count;
      button.setAttribute("aria-pressed", String(value === filter));
      button.addEventListener("click", () => {
        if (busy) return;
        filter = value;
        renderCards();
      });
      container.append(button);
    }
  }
  function renderCards() {
    $("closet-filters").querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.category === filter));
    });
    const shown = items.filter((item) => filter === "all" || normalizeCategory(item.category) === filter);
    $("closet-count").textContent = "총 " + items.length + "개 · 현재 " + shown.length + "개";
    const container = $("closet-list");
    container.replaceChildren();
    $("closet-empty").hidden = shown.length > 0;
    $("closet-empty").textContent = items.length ? "이 분류에 등록된 옷이 없어요." : "아직 등록한 옷이 없어요. 첫 번째 옷을 추가해 보세요.";
    for (const item of shown) {
      const card = document.createElement("article");
      card.className = "wardrobe-card";
      const imageArea = document.createElement("div");
      imageArea.className = "wardrobe-card-image";
      const placeholder = document.createElement("span");
      placeholder.className = "photo-placeholder";
      placeholder.textContent = "사진 없음";
      imageArea.append(placeholder);
      const src = imageSource(item, window.location.origin);
      if (src) {
        placeholder.textContent = "사진을 불러오고 있어요.";
        const img = document.createElement("img");
        img.alt = itemTitle(item);
        img.loading = "lazy";
        img.decoding = "async";
        img.referrerPolicy = "no-referrer";
        img.addEventListener("load", () => { placeholder.hidden = true; });
        img.addEventListener("error", () => {
          img.hidden = true;
          placeholder.hidden = false;
          placeholder.textContent = "사진을 불러오지 못했어요.";
        });
        img.src = src;
        imageArea.append(img);
      }
      const body = document.createElement("div");
      body.className = "wardrobe-card-body";
      const title = document.createElement("h2");
      title.className = "wardrobe-card-title";
      title.textContent = itemTitle(item);
      const meta = document.createElement("p");
      meta.className = "wardrobe-card-meta";
      meta.textContent = categoryLabel(item.category) + " · " + fitLabel(item.fit);
      const seasons = document.createElement("p");
      seasons.className = "wardrobe-card-meta";
      seasons.textContent = item.seasons.length ? item.seasons.map(seasonLabel).join(" · ") : "계절 선택 안 함";
      const actions = document.createElement("div");
      actions.className = "wardrobe-card-actions";
      const edit = document.createElement("a");
      edit.className = "button secondary-button";
      edit.href = "#wardrobe/edit/" + item.item_id;
      edit.textContent = "수정";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button wardrobe-delete";
      remove.textContent = "삭제";
      remove.setAttribute("aria-label", itemTitle(item) + " 삭제");
      remove.addEventListener("click", () => { void deleteItem(item); });
      actions.append(edit, remove);
      body.append(title, meta, seasons, actions);
      card.append(imageArea, body);
      container.append(card);
    }
    buttons();
  }
  async function load(route, notice) {
    const beforeId = getCurrentUser()?.id;
    reset();
    activeRoute = route;
    if (route !== "closet") $("wardrobe-title").textContent = route === "wardrobe/new" ? "옷 추가하기" : "옷 수정하기";
    const ticket = epoch;
    message("옷장 정보를 불러오고 있어요.", "info");
    try {
      const user = await refreshSession();
      if (!live(ticket)) return;
      onSessionChange();
      if (!user) { expire(); return; }
      if (beforeId !== undefined && beforeId !== user.id) { changedAccount(); return; }
      ownerId = user.id;
      if (route === "closet") {
        const data = await authenticatedRequest("/wardrobe");
        if (!live(ticket, ownerId)) return;
        if (!Array.isArray(data)) throw new Error("옷장 목록 응답을 확인하지 못했습니다.");
        // Wardrobe responses have no user_id. Verify the session again before displaying them.
        if (!await verifyOwner(ticket, ownerId)) return;
        items = data.map(validateItem);
        renderFilters();
        renderCards();
      } else if (route === "wardrobe/new") {
        fillEditor(null);
      } else {
        const id = Number(route.split("/")[2]);
        const data = validateItem(await authenticatedRequest("/wardrobe/" + id));
        if (!live(ticket, ownerId)) return;
        if (!await verifyOwner(ticket, ownerId)) return;
        if (data.item_id !== id) throw new Error("요청한 의류와 응답이 일치하지 않습니다.");
        currentItem = data;
        fillEditor(data);
      }
      if (!live(ticket, ownerId)) return;
      ready = true;
      message(notice?.message || "", notice?.kind || "info");
    } catch (error) {
      if (!live(ticket)) return;
      if (error.status === 401) { expire(); return; }
      message(error.message);
      $(route === "closet" ? "closet-retry" : "wardrobe-retry").hidden = false;
    } finally {
      if (live(ticket)) { buttons(); form.setAttribute("aria-busy", "false"); }
    }
  }
  function chooseFile() {
    if (busy) return;
    selectedFile = photo.files?.[0] || null;
    photoRetry = false;
    if (!selectedFile) { clearFile(); message(); return; }
    photoReady = false;
    photoError = "";
    releasePreview();
    $("wardrobe-file-info").textContent = selectedFile.name;
    try { validatePhotoFile(selectedFile); }
    catch (error) {
      photoError = error.message;
      $("wardrobe-photo-placeholder").hidden = false;
      $("wardrobe-photo-placeholder").textContent = "다른 사진을 선택하거나 사진 선택을 취소해 주세요.";
      message(photoError);
      buttons();
      return;
    }
    const ticket = epoch;
    const photoTicket = photoEpoch;
    previewUrl = URL.createObjectURL(selectedFile);
    preview.alt = "선택한 의류 사진 미리보기";
    preview.hidden = false;
    $("wardrobe-photo-placeholder").hidden = true;
    message("사진을 확인하고 있어요.", "info");
    preview.onload = () => {
      if (!live(ticket) || photoTicket !== photoEpoch) return;
      if (!preview.naturalWidth || !preview.naturalHeight
        || preview.naturalWidth * preview.naturalHeight > MAX_IMAGE_PIXELS) {
        photoError = "사진은 가로 × 세로 1,600만 픽셀 이하로 선택해 주세요.";
        photoReady = false;
        message(photoError);
      } else {
        photoReady = true;
        message("사진을 선택했어요. 저장을 누르면 업로드됩니다.", "info");
      }
      buttons();
    };
    preview.onerror = () => {
      if (!live(ticket) || photoTicket !== photoEpoch) return;
      photoError = "사진을 읽지 못했습니다. 다른 JPG, PNG 또는 WEBP 사진을 선택해 주세요.";
      photoReady = false;
      message(photoError);
      buttons();
    };
    preview.src = previewUrl;
    buttons();
  }
  async function save() {
    if (busy || !ready || ownerId === null || !photoReady || photoError || uncertainCreate) return;
    let data;
    try { data = payload(); }
    catch (error) { showValidation(error); return; }
    const ticket = epoch, expectedId = ownerId;
    let createAttempted = false, metadataSaved = false, uploading = false, photoSaved = false;
    busy = true;
    buttons();
    message("저장하고 있어요.", "info");
    try {
      if (!await verifyOwner(ticket, expectedId)) return;
      if (!currentItem) {
        createAttempted = true;
        const created = validateItem(await authenticatedRequest("/wardrobe", { method: "POST", body: data }));
        if (!live(ticket, expectedId)) return;
        currentItem = created;
        metadataSaved = true;
        // Retain the new ID immediately: a failed photo upload must never create another item.
        activeRoute = "wardrobe/edit/" + currentItem.item_id;
        replaceRoute(activeRoute);
        $("wardrobe-title").textContent = "옷 수정하기";
      } else if (!metadataEqual(data, currentItem)) {
        const id = currentItem.item_id;
        const updated = validateItem(await authenticatedRequest("/wardrobe/" + id, { method: "PATCH", body: data }));
        if (!live(ticket, expectedId)) return;
        if (updated.item_id !== id) throw new Error("저장된 의류 정보를 확인하지 못했습니다.");
        currentItem = updated;
        metadataSaved = true;
      }
      if (!await verifyOwner(ticket, expectedId)) return;
      if (selectedFile) {
        uploading = true;
        message("의류 정보가 저장됐어요. 사진을 올리고 있어요.", "info");
        const upload = new FormData();
        upload.append("file", selectedFile);
        const id = currentItem.item_id;
        const updated = validateItem(await authenticatedRequest("/wardrobe/" + id + "/image", {
          method: "POST", body: upload, timeoutMs: 30000,
        }));
        if (!live(ticket, expectedId)) return;
        if (updated.item_id !== id) throw new Error("사진이 저장된 의류 정보를 확인하지 못했습니다.");
        currentItem = updated;
        photoSaved = true;
        uploading = false;
        clearFile();
        if (!await verifyOwner(ticket, expectedId)) return;
      }
      busy = false;
      navigate("closet", { message: "옷장에 저장했어요.", kind: "success" });
    } catch (error) {
      if (!live(ticket)) return;
      if (error.status === 401) { expire(); return; }
      if (photoSaved) {
        message("사진 저장은 완료됐어요. 로그인 상태를 다시 확인해 주세요. " + error.message);
      } else if (uploading && currentItem) {
        photoRetry = true;
        message("의류 정보는 저장됐지만 사진 업로드에 실패했어요. 사진만 다시 올릴 수 있어요. " + error.message);
      } else if (createAttempted && !currentItem && (!error.status || error.status >= 500 || error.status < 400)) {
        uncertainCreate = true;
        message("등록 결과를 확인하지 못했어요. 중복 등록을 피하려면 옷장 목록에서 저장 여부를 확인해 주세요.");
      } else {
        message((metadataSaved ? "의류 정보 저장은 완료됐어요. 현재 상태를 다시 확인해 주세요. " : "") + error.message);
      }
    } finally {
      if (live(ticket)) { busy = false; buttons(); }
    }
  }
  async function deleteItem(item) {
    if (busy || !ready || activeRoute !== "closet") return;
    const ticket = epoch, expectedId = ownerId;
    busy = true;
    buttons();
    try {
      if (!await verifyOwner(ticket, expectedId)) return;
      if (!window.confirm("‘" + itemTitle(item) + "’을(를) 삭제할까요? 등록된 사진도 함께 삭제됩니다.")) return;
      message("삭제하고 있어요.", "info");
      await authenticatedRequest("/wardrobe/" + item.item_id, { method: "DELETE" });
      if (!live(ticket, expectedId)) return;
      if (!await verifyOwner(ticket, expectedId)) return;
      items = items.filter((entry) => entry.item_id !== item.item_id);
      renderFilters();
      renderCards();
      message("옷장에서 삭제했어요.", "success");
    } catch (error) {
      if (!live(ticket)) return;
      if (error.status === 401) { expire(); return; }
      message(error.message + " 목록을 다시 불러와 현재 상태를 확인해 주세요.");
      $("closet-retry").hidden = false;
    } finally {
      if (live(ticket)) { busy = false; buttons(); }
    }
  }
  async function deletePhoto() {
    if (busy || !ready || !currentItem?.image_url || selectedFile) return;
    const ticket = epoch, expectedId = ownerId, id = currentItem.item_id;
    busy = true;
    buttons();
    try {
      if (!await verifyOwner(ticket, expectedId)) return;
      if (!window.confirm("등록된 사진만 삭제할까요? 의류 정보는 유지됩니다.")) return;
      message("사진을 삭제하고 있어요.", "info");
      await authenticatedRequest("/wardrobe/" + id + "/image", { method: "DELETE" });
      if (!live(ticket, expectedId)) return;
      if (!await verifyOwner(ticket, expectedId)) return;
      currentItem = { ...currentItem, image_url: null };
      storedPreview();
      message("사진을 삭제했어요. 의류 정보는 유지됩니다.", "success");
    } catch (error) {
      if (!live(ticket)) return;
      if (error.status === 401) { expire(); return; }
      message(error.message + " 의류를 다시 불러와 사진 상태를 확인해 주세요.");
      $("wardrobe-retry").hidden = false;
    } finally {
      if (live(ticket)) { busy = false; buttons(); }
    }
  }
  form.addEventListener("submit", (event) => { event.preventDefault(); void save(); });
  form.addEventListener("input", () => { if (photoRetry && !busy) { photoRetry = false; buttons(); } });
  photo.addEventListener("change", chooseFile);
  $("wardrobe-clear-file").addEventListener("click", () => {
    if (!busy) { clearFile(); message("사진 선택을 취소했어요.", "info"); }
  });
  $("wardrobe-delete-photo").addEventListener("click", () => { void deletePhoto(); });
  $("closet-retry").addEventListener("click", () => { if (!busy) void load("closet"); });
  $("wardrobe-retry").addEventListener("click", () => { if (!busy) void load(activeRoute); });
  reset();
  return {
    open(route, notice) { return load(route, notice); },
    reset,
    isSaving() { return busy; },
  };
}
