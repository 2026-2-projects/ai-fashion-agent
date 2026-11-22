import { ApiError, apiRequest } from "./api.js";

let currentUser = null;
let csrfToken = null;
let sessionRevision = 0;
let refreshSequence = 0;

function clearSession() {
  currentUser = null;
  csrfToken = null;
  sessionRevision += 1;
}

function acceptSession(data) {
  if (!Number.isInteger(data?.id) || typeof data?.email !== "string"
      || typeof data?.csrf_token !== "string" || !data.csrf_token) {
    throw new ApiError("로그인 정보를 확인하지 못했습니다. 다시 로그인해 주세요.");
  }
  const changed = currentUser?.id !== data.id || currentUser?.email !== data.email
    || csrfToken !== data.csrf_token;
  currentUser = { id: data.id, email: data.email };
  csrfToken = data.csrf_token;
  // Re-reading the same session must not cancel a pending logout of that session.
  if (changed) sessionRevision += 1;
  return getCurrentUser();
}

export function getCurrentUser() {
  return currentUser ? { ...currentUser } : null;
}

/** A 401 means signed out; network/server failures must not look like logout. */
export async function refreshSession() {
  const sequence = ++refreshSequence;
  const revision = sessionRevision;
  const isCurrent = () => sequence === refreshSequence && revision === sessionRevision;
  try {
    const data = await apiRequest("/auth/me");
    // A newer refresh/login/logout owns the state, even if this request arrived later.
    if (!isCurrent()) return getCurrentUser();
    return acceptSession(data);
  } catch (error) {
    if (!isCurrent()) return getCurrentUser();
    if (error.status === 401) {
      clearSession();
      return null;
    }
    throw error;
  }
}

export async function signup(email, password) {
  // Signup creates an account, but does not establish a session.
  return apiRequest("/auth/signup", { method: "POST", body: { email, password } });
}

export async function login(email, password) {
  await apiRequest("/auth/login", { method: "POST", body: { email, password } });
  clearSession();
  // Verify the browser actually stored and sent the session cookie.
  const user = await refreshSession();
  if (!user) {
    throw new ApiError("로그인 정보를 유지하지 못했습니다. 브라우저 설정을 확인하고 다시 시도해 주세요.", 401);
  }
  return user;
}

/** Reusable for the profile, wardrobe and recommendation steps that follow. */
export async function authenticatedRequest(path, options = {}) {
  if (!currentUser || !csrfToken) await refreshSession();
  if (!currentUser) throw new ApiError("로그인이 필요합니다.", 401);

  const method = (options.method || "GET").toUpperCase();
  const changesState = !["GET", "HEAD", "OPTIONS"].includes(method);
  const revision = sessionRevision;
  const sequence = refreshSequence;
  const requestCsrfToken = csrfToken;
  try {
    return await apiRequest(path, {
      ...options,
      method,
      csrfToken: changesState ? requestCsrfToken : undefined,
    });
  } catch (error) {
    // A response for the previous account must not sign out the new account.
    if (error.status === 401 && revision === sessionRevision && sequence === refreshSequence) {
      clearSession();
    }
    throw error;
  }
}

export async function logout() {
  // Another tab may have logged in again and rotated the CSRF token.
  const user = await refreshSession();
  if (!user) return;
  const revision = sessionRevision;
  await authenticatedRequest("/auth/logout", { method: "POST" });
  if (revision === sessionRevision) clearSession();
}

/** Forget local state only after the backend confirms account deletion (204). */
export function finalizeAccountDeletion(expectedUserId) {
  if (!currentUser || currentUser.id !== expectedUserId) return false;
  refreshSequence += 1; // Invalidate stale /auth/me requests.
  clearSession();
  return true;
}
