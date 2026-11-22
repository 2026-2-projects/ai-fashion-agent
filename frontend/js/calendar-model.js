export const CALENDAR_READ_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly";

const AUTHORIZATION_ORIGIN = "https://accounts.google.com";
const AUTHORIZATION_PATH = "/o/oauth2/v2/auth";
const AUTHORIZATION_PARAMETERS = new Set([
  "client_id", "redirect_uri", "response_type", "scope", "access_type",
  "include_granted_scopes", "prompt", "state",
]);

/** A stored connection stays connected even when its access token needs refreshing. */
export function validateConnection(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)
      || typeof data.connected !== "boolean"
      || !(data.scope === null || typeof data.scope === "string")
      || !(data.token_expires_at === null || typeof data.token_expires_at === "string")) {
    throw new Error("Google Calendar 연결 상태 응답을 확인하지 못했어요. 다시 시도해 주세요.");
  }
  return data;
}

function validRedirectUri(value) {
  try {
    const url = new URL(value);
    if (url.username || url.password || value.includes("#")) return false;
    if (url.protocol === "https:") return true;
    // Match the backend's literal localhost/127.0.0.1 allowlist, not alternate IP spellings.
    return url.protocol === "http:"
      && /^http:\/\/(localhost|127\.0\.0\.1)(?::\d+)?(?:[/?]|$)/i.test(value)
      && ["localhost", "127.0.0.1"].includes(url.hostname);
  } catch {
    return false;
  }
}

export function validateOAuthStart(data) {
  const invalid = () => {
    throw new Error("Google Calendar 연결 요청을 확인하지 못했어요. 다시 시도해 주세요.");
  };
  if (!data || typeof data !== "object" || Array.isArray(data)
      || typeof data.authorization_url !== "string"
      || !Number.isInteger(data.expires_in_seconds)
      || data.expires_in_seconds <= 0 || data.expires_in_seconds > 600) invalid();

  let url;
  try { url = new URL(data.authorization_url); }
  catch { invalid(); }
  if (url.origin !== AUTHORIZATION_ORIGIN || url.pathname !== AUTHORIZATION_PATH
      || url.username || url.password || data.authorization_url.includes("#")) invalid();

  const params = url.searchParams;
  const seen = new Set();
  for (const [name] of params) {
    // Backend-generated OAuth URLs contain these fields only, never secrets or tokens.
    if (!AUTHORIZATION_PARAMETERS.has(name) || seen.has(name)) invalid();
    seen.add(name);
  }
  if (params.get("response_type") !== "code" || params.get("scope") !== CALENDAR_READ_SCOPE) invalid();
  for (const name of ["client_id", "redirect_uri", "state"]) {
    if (!params.get(name)?.trim()) invalid();
  }
  if (!validRedirectUri(params.get("redirect_uri"))) invalid();
  if (params.has("access_type") && params.get("access_type") !== "offline") invalid();
  if (params.has("include_granted_scopes") && params.get("include_granted_scopes") !== "false") invalid();
  if (params.has("prompt") && params.get("prompt") !== "consent select_account") invalid();
  return data;
}

export function calendarError(error, operation) {
  if (operation === "start" && error?.status === 503) {
    return "Google Calendar 연결 설정이 아직 준비되지 않았어요. 관리자에게 연결 설정을 확인해 주세요.";
  }
  // API errors and validation errors already use safe messages; never stringify raw responses.
  if (typeof error?.message === "string" && error.message.trim()) return error.message;
  return "Google Calendar 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
}
