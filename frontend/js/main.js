import { getCurrentUser, login, logout, refreshSession, signup } from "./auth.js";
import { createSettingsController } from "./settings.js";
import { createWardrobeController } from "./wardrobe.js";
import { createCalendarController } from "./calendar.js";
import { createRecommendationController } from "./recommendation.js";
import { clearRecommendationSnapshots } from "./recommendation-snapshot.js";
// CLOMORI_RECOMMENDATION_FIXES_V3
import { createSavedController } from "./saved.js";
import { createDataManagementController } from "./data-management.js";

const pages = [...document.querySelectorAll(".page")];
const loginForm = document.querySelector("#login-form");
const signupForm = document.querySelector("#signup-form");
const logoutButton = document.querySelector("#logout-button");
const globalStatus = document.querySelector("#global-status");
const retryButton = document.querySelector("#retry-session");
const protectedPages = new Set(["account", "profile", "preferences", "closet", "wardrobe", "recommendation", "saved", "data"]);
const allowedRoutes = new Set(["home", "login", "signup", "account", "profile", "preferences", "closet", "recommendation", "saved", "data"]);
let initializing = true;
let sessionState = "checking";
let busy = false;
let lastRoute = null;
let lastUserId = null;
let loadedSettingsKey = null;
let loadedWardrobeKey = null;
let loadedCalendarKey = null;
let loadedRecommendationKey = null;
let loadedSavedKey = null;
let loadedDataKey = null;
let pendingWardrobeNotice = null;
let pendingRecommendationNotice = null;
let pendingSavedNotice = null;
let lastBlocked = true;

function setMessage(element, text = "", kind = "error") {
  element.textContent = text;
  element.dataset.kind = kind;
}

function updateNavigation() {
  const user = getCurrentUser();
  document.querySelector("#header-auth-link").textContent = user ? "내 계정" : "로그인";
  document.querySelector("#header-auth-link").href = user ? "#account" : "#login";
  document.querySelector("#start-link").href = user ? "#recommendation" : "#login";
  document.querySelector("#header-closet-link").hidden = !user;
  document.querySelector("#header-recommendation-link").hidden = !user;
  document.querySelector("#header-saved-link").hidden = !user;
  document.querySelector("#account-email").textContent = user?.email || "";
}

const settings = createSettingsController({
  navigate,
  onSessionChange: updateNavigation,
  onSessionExpired: sessionExpired,
});

const wardrobe = createWardrobeController({
  navigate,
  replaceRoute: replaceWardrobeRoute,
  onSessionChange: updateNavigation,
  onSessionExpired: sessionExpired,
});

const calendar = createCalendarController({
  navigate,
  onSessionChange: updateNavigation,
  onSessionExpired: sessionExpired,
  isBlocked: () => busy || initializing,
});

const recommendation = createRecommendationController({
  navigate,
  onSessionChange: updateNavigation,
  onSessionExpired: sessionExpired,
  isBlocked: () => busy || initializing,
});

const saved = createSavedController({
  navigate,
  onSessionChange: updateNavigation,
  onSessionExpired: sessionExpired,
  isBlocked: () => busy || initializing,
});

const dataManagement = createDataManagementController({
  navigate,
  onDataCleared() {
    // Invalidate stale snapshots; the current data summary stays visible.
    settings.reset(); wardrobe.reset(); recommendation.reset(); saved.reset();
    clearRecommendationSnapshots();
    loadedSettingsKey = null; loadedWardrobeKey = null;
    loadedRecommendationKey = null; loadedSavedKey = null;
    pendingWardrobeNotice = null; pendingRecommendationNotice = null; pendingSavedNotice = null;
  },
  onAccountDeleted() {
    resetPrivateViews();
    clearRecommendationSnapshots();
    sessionState = "ready";
    clearGlobalError();
    setMessage(loginForm.querySelector(".form-message"), "계정 탈퇴가 완료됐어요.", "success");
    navigate("login");
  },
  onSessionExpired: sessionExpired,
  isBlocked: () => busy || initializing,
});

function sessionExpired() {
  clearRecommendationSnapshots();
  sessionState = "ready";
  loadedSettingsKey = null;
  loadedWardrobeKey = null;
  loadedCalendarKey = null;
  loadedRecommendationKey = null;
  loadedSavedKey = null;
  loadedDataKey = null;
  pendingWardrobeNotice = null;
  pendingRecommendationNotice = null;
  pendingSavedNotice = null;
  setMessage(loginForm.querySelector(".form-message"), "로그인이 필요해요. 다시 로그인해 주세요.", "info");
  navigate("login");
}

function resetPrivateViews() {
  settings.reset();
  wardrobe.reset();
  calendar.reset();
  recommendation.reset();
  saved.reset();
  dataManagement.reset();
  loadedSettingsKey = null;
  loadedWardrobeKey = null;
  loadedCalendarKey = null;
  loadedRecommendationKey = null;
  loadedSavedKey = null;
  loadedDataKey = null;
}

function setBusy(value) {
  busy = value;
  document.querySelectorAll(".auth-form input, .auth-form button, #logout-button").forEach((control) => {
    control.disabled = value || initializing;
  });
  for (const form of [loginForm, signupForm]) form.setAttribute("aria-busy", String(value));
  calendar.refreshControls();
  recommendation.refreshControls();
  saved.refreshControls();
  dataManagement.refreshControls();
}

function currentRoute() {
  const route = window.location.hash.slice(1) || "home";
  if (allowedRoutes.has(route) || route === "wardrobe/new") return route;
  const match = /^wardrobe\/edit\/([1-9]\d*)$/.exec(route);
  return match && Number.isSafeInteger(Number(match[1])) ? route : "home";
}

function pageForRoute(route) {
  return route.startsWith("wardrobe/") ? "wardrobe" : route;
}

function titleForRoute(route) {
  const titles = {
    home: "CLOMORI", login: "로그인", signup: "회원가입",
    account: "내 계정", profile: "프로필 설정", preferences: "취향 설정",
    closet: "나만의 옷장", wardrobe: route === "wardrobe/new" ? "옷 추가하기" : "옷 수정하기", recommendation: "코디 추천", saved: "저장한 코디", data: "데이터 관리",
  };
  return route === "home" ? titles.home : titles[pageForRoute(route)] + " | CLOMORI";
}

// Keep the newly created item and selected file in memory while uploading its photo.
// Reopening the editor here would clear the draft and lose the photo-only retry state.
function replaceWardrobeRoute(route) {
  history.replaceState(null, "", "#" + route);
  lastRoute = route;
  lastUserId = getCurrentUser()?.id ?? null;
  loadedWardrobeKey = lastUserId + ":" + route;
  document.title = titleForRoute(route);
}

function showPage() {
  const user = getCurrentUser();
  let route = currentRoute();
  if (sessionState === "ready" && protectedPages.has(pageForRoute(route)) && !user) route = "login";
  if (sessionState === "ready" && user && ["login", "signup"].includes(route)) route = "account";
  if ("#" + route !== window.location.hash) history.replaceState(null, "", "#" + route);

  // A failed session check is not a confirmed logout: keep the requested URL and retry UI.
  const pageId = pageForRoute(route);
  const blocked = protectedPages.has(pageId) && sessionState !== "ready";
  const changed = route !== lastRoute || (user?.id ?? null) !== lastUserId;
  if (changed || blocked) {
    resetPrivateViews();
  }
  for (const page of pages) page.hidden = page.id !== pageId || blocked;
  updateNavigation();
  document.title = titleForRoute(route);
  if (!initializing && !blocked && (changed || lastBlocked)) {
    document.querySelector("#" + pageId + " h1")?.focus({ preventScroll: true });
  }

  lastRoute = route;
  lastUserId = user?.id ?? null;
  lastBlocked = blocked;
  if (!blocked && user && ["profile", "preferences"].includes(route)) {
    const key = user.id + ":" + route;
    if (loadedSettingsKey !== key) {
      loadedSettingsKey = key;
      void settings.open(route);
    }
  }
  if (!blocked && user && ["closet", "wardrobe"].includes(pageId)) {
    const key = user.id + ":" + route;
    if (loadedWardrobeKey !== key) {
      loadedWardrobeKey = key;
      const notice = pendingWardrobeNotice;
      pendingWardrobeNotice = null;
      void wardrobe.open(route, notice);
    }
  }
  if (!blocked && user && route === "account") {
    const key = user.id + ":account";
    if (loadedCalendarKey !== key) {
      loadedCalendarKey = key;
      void calendar.open();
    }
  }
  if (!blocked && user && route === "recommendation") {
    const key = user.id + ":recommendation";
    if (loadedRecommendationKey !== key) {
      loadedRecommendationKey = key;
      const notice = pendingRecommendationNotice;
      pendingRecommendationNotice = null;
      void recommendation.open(notice);
    }
  }
  if (!blocked && user && route === "data") {
    const key = user.id + ":data";
    if (loadedDataKey !== key) {
      loadedDataKey = key;
      dataManagement.open();
    }
  }
  if (!blocked && user && route === "saved") {
    const key = user.id + ":saved";
    if (loadedSavedKey !== key) {
      loadedSavedKey = key;
      const notice = pendingSavedNotice;
      pendingSavedNotice = null;
      void saved.open(notice);
    }
  }
}

function navigate(route, notice) {
  if (notice && route === "account") {
    setMessage(document.querySelector("#account-message"), notice.message, notice.kind || "success");
  }
  if (notice && route === "closet") pendingWardrobeNotice = notice;
  if (notice && route === "recommendation") pendingRecommendationNotice = notice;
  if (notice && route === "saved") pendingSavedNotice = notice;
  if (window.location.hash !== "#" + route) window.location.hash = route;
  showPage();
}

function clearGlobalError() {
  setMessage(globalStatus);
  retryButton.hidden = true;
}

async function restoreSession() {
  if (busy || settings.isSaving() || wardrobe.isSaving() || calendar.isSaving() || recommendation.isSaving() || saved.isSaving() || dataManagement.isSaving()) return;
  initializing = true;
  sessionState = "checking";
  setBusy(false);
  resetPrivateViews();
  retryButton.hidden = true;
  setMessage(globalStatus, "로그인 상태를 확인하고 있어요.", "info");
  showPage();
  try {
    await refreshSession();
    sessionState = "ready";
    clearGlobalError();
  } catch (error) {
    sessionState = "error";
    setMessage(globalStatus, error.message);
    retryButton.hidden = false;
  } finally {
    initializing = false;
    setBusy(false);
    showPage();
  }
}

window.addEventListener("hashchange", () => {
  for (const input of document.querySelectorAll('input[type="password"]')) input.value = "";
  showPage();
});
// Keep ordinary link clicks from interrupting a save; late responses are guarded even on browser Back.
document.addEventListener("click", (event) => {
  const link = event.target.closest?.('a[href^="#"]');
  if (link && (busy || settings.isSaving() || wardrobe.isSaving() || calendar.isSaving() || recommendation.isSaving() || saved.isSaving() || dataManagement.isSaving())) event.preventDefault();
});
retryButton.addEventListener("click", restoreSession);

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || initializing) return;
  const message = loginForm.querySelector(".form-message");
  const passwordInput = document.querySelector("#login-password");
  const email = document.querySelector("#login-email").value.trim();
  setBusy(true);
  setMessage(message, "로그인하고 있어요.", "info");
  try {
    await login(email, passwordInput.value);
    sessionState = "ready";
    clearGlobalError();
    loginForm.reset();
    setMessage(message);
    setMessage(document.querySelector("#account-message"));
    if (currentRoute() === "login") navigate("account");
    else showPage();
  } catch (error) {
    setMessage(message, error.message);
  } finally {
    passwordInput.value = "";
    setBusy(false);
  }
});

signupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || initializing) return;
  const message = signupForm.querySelector(".form-message");
  const passwordInput = document.querySelector("#signup-password");
  const confirmation = document.querySelector("#signup-confirm");
  const email = document.querySelector("#signup-email").value.trim();
  const length = Array.from(passwordInput.value).length;

  if (length < 12 || length > 128) {
    setMessage(message, "비밀번호는 12~128자로 입력해 주세요.");
    return;
  }
  if (passwordInput.value !== confirmation.value) {
    setMessage(message, "비밀번호가 일치하지 않습니다.");
    return;
  }

  setBusy(true);
  setMessage(message, "계정을 만들고 있어요.", "info");
  try {
    await signup(email, passwordInput.value);
    clearGlobalError();
    signupForm.reset();
    setMessage(message);
    document.querySelector("#login-email").value = email;
    setMessage(loginForm.querySelector(".form-message"), "회원가입이 완료됐어요. 방금 만든 계정으로 로그인해 주세요.", "success");
    if (currentRoute() === "signup") navigate("login");
    else showPage();
  } catch (error) {
    setMessage(message, error.message);
  } finally {
    passwordInput.value = "";
    confirmation.value = "";
    setBusy(false);
  }
});

logoutButton.addEventListener("click", async () => {
  if (busy || initializing || settings.isSaving() || wardrobe.isSaving() || calendar.isSaving() || recommendation.isSaving() || saved.isSaving() || dataManagement.isSaving()) return;
  const message = document.querySelector("#account-message");
  setBusy(true);
  setMessage(message, "로그아웃하고 있어요.", "info");
  try {
    await logout();
    resetPrivateViews();
    clearRecommendationSnapshots();
    pendingWardrobeNotice = null;
    pendingRecommendationNotice = null;
    pendingSavedNotice = null;
    clearGlobalError();
    setMessage(message);
    setMessage(loginForm.querySelector(".form-message"), "로그아웃됐어요.", "success");
    navigate("login");
  } catch (error) {
    setMessage(message, error.message);
  } finally {
    setBusy(false);
  }
});

showPage();
restoreSession();
