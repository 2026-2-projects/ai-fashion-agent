const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function errorMessage(payload, status) {
  if (status >= 500) {
    return "서버에 연결하거나 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
  }

  if (typeof payload?.detail === "string") return payload.detail;

  if (payload?.detail && typeof payload.detail === "object"
      && !Array.isArray(payload.detail) && typeof payload.detail.message === "string") {
    const candidates = Array.isArray(payload.detail.candidates)
      ? payload.detail.candidates.slice(0, 5).filter((item) => typeof item?.name === "string")
        .map((item) => item.name + (typeof item.address === "string" && item.address ? ` (${item.address})` : ""))
      : [];
    return payload.detail.message + (candidates.length ? " 후보: " + candidates.join(" / ") : "");
  }

  if (Array.isArray(payload?.detail)) {
    const fields = payload.detail.flatMap((error) => Array.isArray(error.loc) ? error.loc : []);
    if (fields.includes("email")) return "올바른 이메일 주소를 입력해 주세요.";
    if (fields.includes("password")) {
      return "비밀번호는 12~128자로 입력해 주세요.";
    }
    if (fields.includes("height_cm")) return "키는 1~300 사이의 정수(cm)로 입력해 주세요.";
    if (fields.includes("body_type")) return "체형은 50자 이내로 입력해 주세요.";
    if (fields.includes("gender") || fields.includes("age_group")) {
      return "성별과 연령대는 각각 30자 이내로 입력해 주세요.";
    }
    if (fields.includes("preferred_fit")) return "선호하는 핏은 50자 이내로 입력해 주세요.";
    if (fields.some((field) => ["preferred_styles", "preferred_colors", "disliked_colors"].includes(field))) {
      return "패션 취향의 선택 내용을 확인해 주세요.";
    }
    return "입력한 내용을 확인해 주세요.";
  }

  if (status === 401) return "로그인이 필요합니다.";
  if (status === 403) return "요청을 확인하지 못했습니다. 로그인 상태를 다시 확인해 주세요.";
  if (status === 404) return "요청한 정보를 찾을 수 없습니다.";
  return `요청을 처리하지 못했습니다. (HTTP ${status})`;
}

/** Cookie storage belongs to the browser. Do not store passwords or tokens here. */
export async function apiRequest(path, options = {}) {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("..")) {
    throw new Error("API path must be relative to /api/v1.");
  }

  const { method = "GET", body, csrfToken, timeoutMs = 15000 } = options;
  const headers = new Headers({ Accept: "application/json" });
  let requestBody;

  if (body instanceof FormData) {
    requestBody = body; // The browser sets the multipart boundary.
  } else if (body !== undefined) {
    headers.set("Content-Type", "application/json");
    requestBody = JSON.stringify(body);
  }

  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_PREFIX}${path}`, {
      method,
      headers,
      body: requestBody,
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });

    // Logout returns 204 without a JSON body.
    if (response.status === 204) return null;

    const raw = await response.text();
    let payload = null;
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        // An upstream error may be plain text (for example, Internal Server Error).
        // Keep its HTTP status and a friendly message without exposing raw details.
        if (response.ok) {
          throw new ApiError("서버 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.", response.status);
        }
      }
    }

    if (!response.ok) {
      throw new ApiError(errorMessage(payload, response.status), response.status);
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error.name === "AbortError") {
      throw new ApiError("요청 시간이 초과되었습니다. 연결 상태를 확인하고 다시 시도해 주세요.");
    }
    throw new ApiError("서버에 연결할 수 없습니다. 연결 상태를 확인해 주세요.");
  } finally {
    window.clearTimeout(timer);
  }
}
