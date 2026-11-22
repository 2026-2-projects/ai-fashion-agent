import { authenticatedRequest, getCurrentUser, refreshSession } from "./auth.js";
import { validateConnection, validateOAuthStart, calendarError } from "./calendar-model.js";

export function createCalendarController({ navigate, onSessionChange, onSessionExpired, isBlocked = () => false }) {
  const $ = (id) => document.getElementById(id);
  let epoch = 0;
  let active = false, ownerId = null, busy = false, ready = false;
  let connection = null, pending = null, reservation = null, expiryTimer = null;
  let operation = "", revocationUnconfirmed = false;

  function live(ticket, expectedId) {
    return active && ticket === epoch && window.location.hash === "#account"
      && (expectedId === undefined || getCurrentUser()?.id === expectedId);
  }
  function message(text = "", kind = "error") {
    $("calendar-message").textContent = text;
    $("calendar-message").dataset.kind = kind;
  }
  function closePopup(popup) {
    try { if (popup && !popup.closed) popup.close(); } catch { /* Cross-origin/closed window. */ }
  }
  function clearPending(close = false) {
    if (expiryTimer !== null) window.clearTimeout(expiryTimer);
    expiryTimer = null;
    if (close) closePopup(pending?.popup);
    pending = null;
    $("calendar-consent-link").removeAttribute("href");
  }
  function render() {
    const locked = busy || isBlocked();
    const connected = connection?.connected === true;
    const status = $("calendar-status");
    status.dataset.state = connection === null ? "unknown" : connected ? "connected" : "disconnected";
    if (busy && ["load", "check"].includes(operation)) status.textContent = "연결 상태 확인 중";
    else if (pending) status.textContent = "Google 권한 동의 대기 중";
    else status.textContent = connection === null ? "연결 상태 확인 필요" : connected ? "연결됨" : "연결되지 않음";
    $("calendar-description").textContent = connected
      ? "일정 조회 권한의 연결 정보가 저장돼 있어요."
      : "추천에 기본 캘린더의 일정을 활용해요.";
    $("calendar-connect").hidden = connected;
    $("calendar-connect").disabled = locked || !ready || !!pending || connection?.connected !== false;
    $("calendar-disconnect").hidden = !connected;
    $("calendar-disconnect").disabled = locked || !ready || !!pending;
    $("calendar-check").disabled = locked || !active;
    $("calendar-consent").hidden = !pending;
    $("calendar-restart").hidden = !pending;
    $("calendar-restart").disabled = locked || !ready;
    $("calendar-connect").textContent = busy && operation === "start" ? "연결 준비 중…" : "Google Calendar 연결하기";
    $("calendar-disconnect").textContent = busy && operation === "disconnect" ? "연결 해제 중…" : "연결 해제";
    $("calendar-check").textContent = busy && operation === "check" ? "확인 중…" : "연결 상태 확인";
    $("calendar-permissions-link").hidden = !revocationUnconfirmed;
  }
  function reset() {
    epoch += 1;
    active = false;
    ownerId = null;
    busy = false;
    ready = false;
    operation = "";
    connection = null;
    revocationUnconfirmed = false;
    closePopup(reservation);
    reservation = null;
    // Navigation does not authorize closing a Google page the user is still using.
    clearPending();
    message();
    render();
  }
  function expire() {
    reset();
    onSessionExpired();
  }
  function changedAccount() {
    reset();
    navigate("account", {
      message: "로그인 계정이 바뀌었어요. 현재 계정의 Calendar 연결 상태를 다시 확인해 주세요.",
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
  async function readConnection(ticket, expectedId) {
    if (!await verifyOwner(ticket, expectedId)) return null;
    const data = validateConnection(await authenticatedRequest("/calendar/connection"));
    if (!live(ticket, expectedId)) return null;
    // The connection response has no user_id; verify the owner before displaying it.
    if (!await verifyOwner(ticket, expectedId)) return null;
    return data;
  }
  async function open() {
    const beforeId = getCurrentUser()?.id;
    reset();
    active = true;
    const ticket = epoch;
    busy = true;
    operation = "load";
    render();
    try {
      const user = await refreshSession();
      if (!live(ticket)) return;
      onSessionChange();
      if (!user) { expire(); return; }
      if (beforeId !== undefined && beforeId !== user.id) { changedAccount(); return; }
      ownerId = user.id;
      const data = validateConnection(await authenticatedRequest("/calendar/connection"));
      if (!live(ticket, ownerId)) return;
      if (!await verifyOwner(ticket, ownerId)) return;
      connection = data;
      ready = true;
      message();
    } catch (error) {
      if (!live(ticket)) return;
      if (error.status === 401) { expire(); return; }
      connection = null;
      ready = false;
      message(calendarError(error, "load") + " ‘연결 상태 확인’으로 다시 확인해 주세요.");
    } finally {
      if (live(ticket)) { busy = false; operation = ""; render(); }
    }
  }
  function reservePopup() {
    let popup = null;
    try {
      popup = window.open("about:blank", "_blank", "popup=yes,width=540,height=740");
      if (popup) {
        popup.opener = null;
        popup.document.title = "Google Calendar 연결 준비";
        popup.document.body.textContent = "Google 인증 화면을 준비하고 있어요. 잠시 기다려 주세요.";
      }
    } catch {
      closePopup(popup);
      popup = null;
    }
    return popup;
  }
  function setExpiry(ticket, flow) {
    expiryTimer = window.setTimeout(() => {
      if (!live(ticket) || pending !== flow) return;
      clearPending();
      // The OAuth callback may already have succeeded. Do not infer disconnection from this timer.
      connection = null;
      ready = false;
      message("인증 안내의 유효 시간이 지났어요. ‘연결 상태 확인’으로 현재 상태를 확인한 뒤 다시 연결해 주세요.", "info");
      render();
    }, flow.expiresIn * 1000);
  }
  async function start() {
    if (isBlocked() || busy || !ready || pending || connection?.connected !== false || ownerId === null) return;
    const ticket = epoch, expectedId = ownerId;
    // Open during the click gesture; the validated server URL is assigned after the request.
    const popup = reservePopup();
    reservation = popup;
    let handedOff = false;
    busy = true;
    operation = "start";
    message("Google 연결을 준비하고 있어요.", "info");
    render();
    try {
      if (!await verifyOwner(ticket, expectedId)) return;
      const data = validateOAuthStart(await authenticatedRequest("/calendar/oauth/start", { method: "POST" }));
      if (!live(ticket, expectedId)) return;
      pending = { url: data.authorization_url, expiresIn: data.expires_in_seconds, popup: null };
      $("calendar-consent-link").href = data.authorization_url;
      if (popup) {
        try {
          if (!popup.closed) {
            popup.location.href = data.authorization_url;
            pending.popup = popup;
            handedOff = true;
          }
        } catch { /* The explicit link remains available if a popup cannot navigate. */ }
      }
      reservation = null;
      setExpiry(ticket, pending);
      message(handedOff
        ? "Google 창에서 계정 선택과 권한 동의를 마친 뒤, 이 화면으로 돌아와 ‘연결 상태 확인’을 눌러 주세요."
        : "새 창을 열지 못했어요. 아래 ‘Google 권한 동의 화면 열기’를 눌러 진행한 뒤 연결 상태를 확인해 주세요.", "info");
      // No automatic polling here: start stores OAuth state in the session cookie.
      // In-flight reads must not race the callback's one-time cookie state update.
    } catch (error) {
      if (!live(ticket)) return;
      if (error.status === 401) { expire(); return; }
      message(calendarError(error, "start"));
    } finally {
      if (!handedOff) closePopup(popup);
      if (reservation === popup) reservation = null;
      if (live(ticket)) { busy = false; operation = ""; render(); }
    }
  }
  async function check() {
    if (isBlocked() || !active || busy) return;
    if (ownerId === null) { await open(); return; }
    const ticket = epoch, expectedId = ownerId;
    busy = true;
    operation = "check";
    message("연결 상태를 확인하고 있어요.", "info");
    render();
    try {
      const data = await readConnection(ticket, expectedId);
      if (!data || !live(ticket, expectedId)) return;
      connection = data;
      ready = true;
      if (data.connected) {
        clearPending(true);
        revocationUnconfirmed = false;
        message("Google Calendar 연결 정보를 확인했어요.", "success");
      } else if (pending) {
        message("아직 연결이 확인되지 않았어요. Google 창에서 동의를 완료해 주세요. 취소했거나 실패했다면 ‘연결 다시 시작’을 눌러 주세요.", "info");
      } else {
        message(revocationUnconfirmed
          ? "이 서비스의 연결은 해제돼 있어요. Google 계정에서도 앱 권한을 확인해 주세요."
          : "현재 연결된 Google Calendar가 없어요.", "info");
      }
    } catch (error) {
      if (!live(ticket)) return;
      if (error.status === 401) { expire(); return; }
      connection = null;
      ready = false;
      message(calendarError(error, "check") + " 연결 상태를 다시 확인해 주세요.");
    } finally {
      if (live(ticket)) { busy = false; operation = ""; render(); }
    }
  }
  async function disconnect() {
    if (isBlocked() || busy || !ready || pending || !connection?.connected || ownerId === null) return;
    if (!window.confirm("Google Calendar 연결을 해제할까요? 해제하면 새 코디 추천에서 Google 일정을 불러올 수 없어요.")) return;
    const ticket = epoch, expectedId = ownerId;
    let attempted = false, accepted = false, deleteError = null;
    busy = true;
    operation = "disconnect";
    message("Calendar 연결을 해제하고 있어요.", "info");
    render();
    try {
      if (!await verifyOwner(ticket, expectedId)) return;
      attempted = true;
      try {
        await authenticatedRequest("/calendar/connection", { method: "DELETE", timeoutMs: 30000 });
        accepted = true;
      } catch (error) {
        if (error.status === 401) throw error;
        deleteError = error;
      }
      if (!live(ticket, expectedId)) return;
      if (deleteError && (!deleteError.status || deleteError.status >= 500 || deleteError.status < 400)) {
        revocationUnconfirmed = true;
      }
      // A 502 may mean local tokens were deleted but Google revocation failed.
      const data = await readConnection(ticket, expectedId);
      if (!data || !live(ticket, expectedId)) return;
      connection = data;
      ready = true;
      if (!data.connected) {
        revocationUnconfirmed = !!deleteError;
        message(deleteError
          ? "이 서비스의 연결은 해제됐지만 Google 쪽 권한 철회 여부를 확인하지 못했어요. 아래 Google 계정 설정에서 앱 권한을 확인해 주세요."
          : "Google Calendar 연결을 해제했어요.", deleteError ? "info" : "success");
      } else {
        revocationUnconfirmed = false;
        message((deleteError ? calendarError(deleteError, "disconnect") + " " : "")
          + "현재 연결 정보가 남아 있어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.");
      }
    } catch (error) {
      if (!live(ticket)) return;
      if (error.status === 401) { expire(); return; }
      connection = null;
      ready = false;
      const prefix = accepted ? "연결 해제 요청은 처리됐지만 현재 상태를 불러오지 못했어요. "
        : attempted ? "연결 해제 결과를 확인하지 못했어요. " : calendarError(error, "disconnect") + " ";
      message(prefix + "‘연결 상태 확인’으로 현재 상태를 확인해 주세요.");
    } finally {
      if (live(ticket)) { busy = false; operation = ""; render(); }
    }
  }
  $("calendar-connect").addEventListener("click", () => { void start(); });
  $("calendar-check").addEventListener("click", () => { void check(); });
  $("calendar-disconnect").addEventListener("click", () => { void disconnect(); });
  $("calendar-restart").addEventListener("click", () => {
    if (isBlocked() || busy || !ready || !pending) return;
    if (!window.confirm("열려 있는 이전 Google 인증 창을 닫은 뒤 진행해 주세요. 새 연결을 시작할까요?")) return;
    clearPending(true);
    render();
    void start();
  });
  $("calendar-consent-link").addEventListener("click", (event) => {
    if (isBlocked() || busy || !pending || !ready) { event.preventDefault(); return; }
    try {
      if (pending.popup && !pending.popup.closed) {
        pending.popup.focus();
        event.preventDefault();
      }
    } catch { /* User can open the validated URL through the explicit link. */ }
  });
  reset();
  return { open, reset, refreshControls: render, isSaving() { return busy; } };
}
