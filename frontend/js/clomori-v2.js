/** CLOMORI V2 – appearance and 24h clock helper only. No API or user data storage. */
/** Normalize convenient 24-hour entries into canonical HH:mm. Invalid values are retained for model validation. */
export function normalize24Hour(value) {
  const s = String(value ?? "").trim();
  if (!s) return "";
  let hours, minutes;
  let m = /^(\d{1,2}):(\d{1,2})$/.exec(s);
  if (m) { hours = Number(m[1]); minutes = Number(m[2]); }
  else if (/^\d{3,4}$/.test(s)) { hours = Number(s.slice(0,-2)); minutes = Number(s.slice(-2)); }
  else if (/^\d{1,2}$/.test(s)) { hours = Number(s); minutes = 0; }
  else return s;
  return hours <= 23 && minutes <= 59 ? `${String(hours).padStart(2,"0")}:${String(minutes).padStart(2,"0")}` : s;
}

/** Preserve original input ID consumed by recommendation.js. */
function activate24HourTime() {
  const input = document.getElementById("recommendation-time");
  if (!input || input.dataset.cmTimeEnhanced === "true") return;
  input.dataset.cmTimeEnhanced = "true";
  function normalize() {
    const updated = normalize24Hour(input.value);
    if (input.value !== updated) {
      input.value = updated;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  input.addEventListener("blur", normalize);
  input.addEventListener("change", normalize);
  // The owning recommendation controller handles submission. Normalize first without cancelling submit.
  document.getElementById("recommendation-form")?.addEventListener("submit", normalize, { capture: true });
}

// CLOMORI_RECOMMENDATION_FIXES_V3
// Recommendation.js renders LOOK 1–5 in API order with equal-size cards.

/** Mobile navigation follows the application's existing #routes; never bypasses authentication. */
function installMobileNav() {
  const nav = document.getElementById("cm-mobile-nav");
  if (!nav) return;
  const appPages = [...document.querySelectorAll(".page")];
  const protectedRoutes = new Set(["recommendation", "closet", "saved", "account", "profile", "preferences", "wardrobe", "data"]);
  const routeAlias = { profile: "account", preferences: "account", wardrobe: "closet", data: "account" };
  function update() {
    const page = appPages.find(p => !p.hidden);
    const route = page?.id ?? "home";
    // CLOMORI_MOBILE_NAV_V6
    // Home uses the bottom bar only when authentication has been verified.
    // The existing auth-controlled header link is the same state used by main.js.
    const homeSignedIn = route === "home"
      && document.getElementById("header-recommendation-link")?.hidden === false;
    const hide = !protectedRoutes.has(route) && !homeSignedIn;
    if (nav.hidden !== hide) nav.hidden = hide;
    const activeRoute = routeAlias[route] || route;
    for (const a of nav.querySelectorAll("a[data-route]")) {
      if (a.dataset.route === activeRoute) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
  }
  new MutationObserver(update).observe(document.body, { attributes: true, attributeFilter: ["hidden"], subtree: true });
  window.addEventListener("hashchange", update);
  update();
}

function start() { activate24HourTime(); installMobileNav(); }
if (typeof document !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
}
