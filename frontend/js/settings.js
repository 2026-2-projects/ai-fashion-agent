import { getCurrentUser, refreshSession, authenticatedRequest } from "./auth.js";
import { ApiError } from "./api.js";

const OPTIONS = {
  preferred_styles: [["minimal", "미니멀"], ["casual", "캐주얼"], ["street", "스트릿"], ["classic", "클래식"]],
  preferred_colors: [["black", "Black"], ["white", "White"], ["navy", "Navy"], ["beige", "Beige"]],
  disliked_colors: [["red", "Red"], ["pink", "Pink"], ["yellow", "Yellow"]],
  preferred_fit: [["slim", "Slim"], ["regular", "Regular"], ["wide", "Wide"], ["oversized", "Oversized"]],
};
const CONTAINERS = {
  preferred_styles: "preferred-styles-options", preferred_colors: "preferred-colors-options",
  disliked_colors: "disliked-colors-options", preferred_fit: "preferred-fit-options",
};

export function createSettingsController({ navigate, onSessionChange, onSessionExpired }) {
  const $ = (id) => document.getElementById(id);
  const forms = { profile: $("profile-form"), preferences: $("preferences-form") };
  const fields = { profile: $("profile-fields"), preferences: $("preferences-fields") };
  const owner = { profile: null, preferences: null };
  const loadedArrays = { preferred_styles: [], preferred_colors: [], disliked_colors: [] };
  let epoch = 0;
  let activeRoute = null;
  let saving = false;

  function message(route, text = "", kind = "error") {
    $(`${route}-message`).textContent = text;
    $(`${route}-message`).dataset.kind = kind;
  }

  function lock(route, value) {
    fields[route].disabled = value;
    forms[route].setAttribute("aria-busy", String(value));
    $("profile-skip").disabled = saving;
    $("preferences-back").disabled = saving;
  }

  function currentTask(ticket, route) {
    return ticket === epoch && route === activeRoute;
  }

  function live(ticket, route, userId) {
    return currentTask(ticket, route) && window.location.hash === `#${route}`
      && (userId === undefined || getCurrentUser()?.id === userId);
  }

  function updateOtherField() {
    const other = $("profile-body-type").value === "__other__";
    $("profile-body-other").hidden = !other;
    $("profile-body-custom").required = other;
  }

  function choices(name, selected) {
    const container = $(CONTAINERS[name]);
    container.replaceChildren();
    const options = [...OPTIONS[name]];
    const known = new Set(options.map(([value]) => value));
    for (const value of selected) {
      if (!known.has(value)) {
        options.push([value, `${value || "빈 값"} (기존)`]);
        known.add(value);
      }
    }
    function add(value, label, none = false) {
      const wrapper = document.createElement("label");
      wrapper.className = "choice";
      const input = document.createElement("input");
      input.type = name === "preferred_fit" ? "radio" : "checkbox";
      input.name = name;
      input.value = value;
      if (none) input.dataset.none = "true";
      input.checked = none ? selected.length === 0 : selected.includes(value);
      const text = document.createElement("span");
      text.className = "choice-label";
      text.textContent = label;
      wrapper.append(input, text);
      container.append(wrapper);
    }
    for (const [value, label] of options) add(value, label);
    if (name === "disliked_colors") add("__none__", "없음", true);
  }

  function reset() {
    epoch += 1;
    activeRoute = null;
    saving = false;
    for (const route of Object.keys(forms)) {
      owner[route] = null;
      forms[route].reset();
      lock(route, true);
      forms[route].setAttribute("aria-busy", "false");
      $(`${route}-retry`).hidden = true;
      message(route);
    }
    for (const select of [$("profile-gender"), $("profile-age-group")]) {
      select.querySelectorAll("option[data-existing]").forEach((option) => option.remove());
      select.value = "";
    }
    for (const name of Object.keys(OPTIONS)) choices(name, []);
    for (const name of Object.keys(loadedArrays)) loadedArrays[name] = [];
    updateOtherField();
  }

  function selectExisting(id, value) {
    const select = $(id);
    select.querySelectorAll("option[data-existing]").forEach((option) => option.remove());
    if (value !== null && ![...select.options].some((option) => option.value === value)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = `${value} (기존)`;
      option.dataset.existing = "true";
      select.append(option);
    }
    select.value = value ?? "";
  }

  function fill(route, data) {
    if (route === "profile") {
      if (!["gender", "age_group", "body_type"].every((key) => data[key] === null || typeof data[key] === "string")
        || !(data.height_cm === null || Number.isInteger(data.height_cm))) {
        throw new ApiError("프로필 응답을 확인하지 못했습니다. 다시 불러와 주세요.");
      }
      selectExisting("profile-gender", data.gender);
      selectExisting("profile-age-group", data.age_group);
      $("profile-height").value = data.height_cm ?? "";
      const known = [...$("profile-body-type").options].some((option) => option.value === data.body_type && option.value !== "__other__");
      $("profile-body-type").value = data.body_type === null ? "" : known ? data.body_type : "__other__";
      $("profile-body-custom").value = known || data.body_type === null ? "" : data.body_type;
      updateOtherField();
    } else {
      for (const name of ["preferred_styles", "preferred_colors", "disliked_colors"]) {
        if (!Array.isArray(data[name]) || !data[name].every((value) => typeof value === "string")) {
          throw new ApiError("취향 응답을 확인하지 못했습니다. 다시 불러와 주세요.");
        }
      }
      if (!(data.preferred_fit === null || typeof data.preferred_fit === "string")) {
        throw new ApiError("취향 응답을 확인하지 못했습니다. 다시 불러와 주세요.");
      }
      for (const name of Object.keys(loadedArrays)) loadedArrays[name] = [...data[name]];
      for (const name of Object.keys(OPTIONS)) {
        choices(name, name === "preferred_fit" ? (data[name] === null ? [] : [data[name]]) : data[name]);
      }
    }
  }

  function expire() {
    reset();
    onSessionExpired();
  }

  async function load(route, notice = "", canReload = true) {
    const ticket = ++epoch;
    const beforeId = getCurrentUser()?.id;
    activeRoute = route;
    owner[route] = null;
    lock(route, true);
    $(`${route}-retry`).hidden = true;
    message(route, "저장된 정보를 불러오고 있어요.", "info");
    try {
      const user = await refreshSession();
      if (!live(ticket, route)) return;
      onSessionChange();
      if (!user) { expire(); return; }
      if (user.id !== beforeId) {
        reset();
        return load(route, "로그인 계정이 변경되어 해당 계정의 정보를 불러왔어요.", false);
      }
      const data = await authenticatedRequest(`/${route}/me`);
      if (!live(ticket, route, user.id)) return;
      if (data?.user_id !== user.id) {
        if (canReload) {
          reset();
          return load(route, "계정 정보를 다시 확인했어요. 현재 계정의 내용을 확인해 주세요.", false);
        }
        throw new ApiError("계정 정보를 확인하지 못했습니다. 다시 불러와 주세요.");
      }
      fill(route, data);
      owner[route] = user.id;
      lock(route, false);
      message(route, notice, "info");
    } catch (error) {
      if (!live(ticket, route)) return;
      if (error.status === 401) { expire(); return; }
      message(route, error.message);
      $(`${route}-retry`).hidden = false;
    } finally {
      if (currentTask(ticket, route)) forms[route].setAttribute("aria-busy", "false");
    }
  }

  function invalid(route, text, element) {
    message(route, text);
    element?.focus();
    return null;
  }

  function profilePayload() {
    const height = $("profile-height");
    const rawHeight = height.value.trim();
    const heightValue = rawHeight === "" ? null : Number(rawHeight);
    if (height.validity.badInput || (heightValue !== null
      && (!Number.isInteger(heightValue) || heightValue < 1 || heightValue > 300))) {
      return invalid("profile", "키는 1~300 사이의 정수로 입력하거나 비워 주세요.", height);
    }
    const other = $("profile-body-type").value === "__other__";
    const custom = $("profile-body-custom");
    if (other && (!custom.value.trim() || Array.from(custom.value).length > 50)) {
      return invalid("profile", "기타 체형 설명을 1~50자로 입력해 주세요.", custom);
    }
    return {
      gender: $("profile-gender").value || null,
      age_group: $("profile-age-group").value || null,
      height_cm: heightValue,
      body_type: other ? custom.value : $("profile-body-type").value || null,
    };
  }

  function preferencesPayload() {
    const checked = (name) => [...$(CONTAINERS[name]).querySelectorAll("input:checked")];
    const selected = Object.fromEntries(Object.keys(OPTIONS).map((name) => [name, checked(name)]));
    const required = [
      ["preferred_styles", "선호하는 스타일을 하나 이상 선택해 주세요."],
      ["preferred_colors", "선호하는 색을 하나 이상 선택해 주세요."],
      ["disliked_colors", "선호하지 않는 색 또는 ‘없음’을 선택해 주세요."],
      ["preferred_fit", "선호하는 핏을 선택해 주세요."],
    ];
    for (const [name, text] of required) {
      const meaningful = selected[name].some((input) => input.value.trim().length > 0);
      if (!selected[name].length || (name !== "disliked_colors" && !meaningful)
        || (name === "preferred_fit" && selected[name].length !== 1)) {
        return invalid("preferences", text, $(CONTAINERS[name]).querySelector("input"));
      }
    }
    function preservedValues(name) {
      const checkedValues = selected[name].filter((input) => !input.dataset.none).map((input) => input.value);
      const checkedSet = new Set(checkedValues);
      const originalSet = new Set(loadedArrays[name]);
      // Order is meaningful to the recommender; preserve existing duplicates too.
      return [
        ...loadedArrays[name].filter((value) => checkedSet.has(value)),
        ...checkedValues.filter((value) => !originalSet.has(value)),
      ];
    }
    const result = {
      preferred_styles: preservedValues("preferred_styles"),
      preferred_colors: preservedValues("preferred_colors"),
      disliked_colors: preservedValues("disliked_colors"),
      preferred_fit: selected.preferred_fit[0].value,
    };
    const normalize = (value) => value.normalize("NFKC").trim().toLowerCase();
    const liked = new Set(result.preferred_colors.map(normalize).filter(Boolean));
    if (result.disliked_colors.some((value) => liked.has(normalize(value)))) {
      return invalid("preferences", "같은 색을 선호하는 색과 선호하지 않는 색에 동시에 선택할 수 없어요.", selected.disliked_colors[0]);
    }
    return result;
  }

  async function save(route) {
    if (saving || activeRoute !== route || owner[route] === null || fields[route].disabled) return;
    const payload = route === "profile" ? profilePayload() : preferencesPayload();
    if (!payload) return;
    const ticket = epoch;
    const expectedId = owner[route];
    saving = true;
    lock(route, true);
    message(route, "저장하고 있어요.", "info");
    try {
      const user = await refreshSession();
      if (!live(ticket, route)) return;
      onSessionChange();
      if (!user) { expire(); return; }
      // Never send a previous account's draft with the new account's cookie.
      if (user.id !== expectedId) {
        reset();
        return load(route, "로그인 계정이 변경되어 입력 내용을 저장하지 않았어요. 현재 계정의 내용을 확인해 주세요.", false);
      }
      const data = await authenticatedRequest(`/${route}/me`, { method: "PATCH", body: payload });
      if (!live(ticket, route, expectedId)) return;
      if (data?.user_id !== expectedId) {
        reset();
        return load(route, "계정 변경이 감지됐어요. 현재 계정의 저장 내용을 다시 확인해 주세요.", false);
      }
      fill(route, data);
      message(route, "저장했어요.", "success");
      saving = false;
      lock(route, false);
      // Navigation only follows a successful response for this form and user.
      if (route === "profile") navigate("preferences");
      else navigate("account", { message: "패션 취향을 저장했어요.", kind: "success" });
    } catch (error) {
      if (!live(ticket, route)) return;
      if (error.status === 401) { expire(); return; }
      // Keep the draft on validation, CSRF, server and network failures.
      message(route, error.message);
    } finally {
      if (currentTask(ticket, route)) {
        saving = false;
        lock(route, owner[route] === null);
      }
    }
  }

  for (const route of Object.keys(forms)) {
    forms[route].addEventListener("submit", (event) => {
      event.preventDefault();
      void save(route);
    });
    $(`${route}-retry`).addEventListener("click", () => { if (!saving) void load(route); });
  }
  $("profile-body-type").addEventListener("change", updateOtherField);
  $("disliked-colors-options").addEventListener("change", (event) => {
    const input = event.target;
    if (input.tagName !== "INPUT" || !input.checked) return;
    for (const other of $("disliked-colors-options").querySelectorAll("input")) {
      if (other !== input && (input.dataset.none || other.dataset.none)) other.checked = false;
    }
  });
  $("profile-skip").addEventListener("click", () => { if (!saving) navigate("preferences"); });
  $("preferences-back").addEventListener("click", () => { if (!saving) navigate("profile"); });
  reset();
  return {
    open(route) { if (!saving && Object.hasOwn(forms, route)) return load(route); },
    reset,
    isSaving() { return saving; },
  };
}
