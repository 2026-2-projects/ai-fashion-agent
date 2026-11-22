import { authenticatedRequest, getCurrentUser } from "./auth.js";
import {
  FEEDBACK_REASON_LABELS, FEEDBACK_TEXT_LIMIT, buildFeedbackPayload, validateInteraction,
  validateInteractions, interactionError,
} from "./interaction-model.js";

const SUCCESS_NOTICE_MS = 3000;

/** Shared LOOK actions. A host supplies a route-scoped session/owner check. */
export function createLookInteractions({ captureContext, isBlocked, onBusyChange, onChange = () => {} }) {
  let epoch = 0, busy = false;
  const records = new Map();
  let views = [];

  function element(tag, className = "", text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function recordFor(recommendationId) {
    if (!records.has(recommendationId)) records.set(recommendationId, {
      phase: "idle", states: new Map(), expected: new Map(), message: "", kind: "info",
      notices: new Map(), drafts: new Map(), errorLookId: null,
    });
    return records.get(recommendationId);
  }
  function capture() {
    const host = captureContext(), version = epoch;
    return host ? { ...host, current: () => epoch === version && host.live() } : null;
  }
  async function verify(context) {
    return Boolean(context?.current() && await context.verify() && context.current());
  }
  function expireIfNeeded(context, error) {
    if (!context?.current() || error.status !== 401) return false;
    const id = getCurrentUser()?.id;
    if (id === undefined || id === context.ownerId) context.expire();
    else context.ownerChanged?.();
    return true;
  }
  function setBusy(value) {
    busy = value;
    onBusyChange(value);
    refreshControls();
  }
  function reset() {
    epoch += 1;
    for (const record of records.values()) clearNotices(record);
    records.clear(); views = [];
    busy = false;
    onBusyChange(false);
  }
  function beginRender() { views = []; }
  function clearNotices(record) {
    for (const entry of record.notices.values()) window.clearTimeout(entry.timer);
    record.notices.clear();
  }
  function updateStatus(view, record) {
    const ownNotice = record.notices.get(view.look.look_id);
    view.status.dataset.kind = ownNotice?.kind || record.kind;
    view.status.textContent = ownNotice?.text || record.message
      || (record.phase === "idle" && !view.savedOnly ? "평가·저장 상태를 확인하고 있어요." : "");
  }
  function notice(record, lookId, text, kind = "info") {
    window.clearTimeout(record.notices.get(lookId)?.timer);
    const entry = { text, kind }, version = epoch;
    record.notices.set(lookId, entry);
    if (kind === "success" && text) entry.timer = window.setTimeout(() => {
      if (epoch !== version || record.notices.get(lookId) !== entry) return;
      record.notices.delete(lookId);
      // Clear only the status text: keep focus, caret and in-progress Korean input.
      for (const view of views) {
        if (view.look.look_id === lookId && records.get(view.recommendationId) === record) updateStatus(view, record);
      }
    }, SUCCESS_NOTICE_MS);
  }
  function reasonDraft(record, lookId, state) {
    if (!record.drafts.has(lookId)) record.drafts.set(lookId, {
      reason: state?.reason || null,
      text: state?.reason === "other" ? state.reason_text || "" : "",
      dirty: false,
    });
    return record.drafts.get(lookId);
  }
  function refreshControls() {
    for (const view of views) {
      const record = recordFor(view.recommendationId);
      const unavailable = record.phase !== "ready" && !(view.savedOnly && record.phase === "idle");
      for (const control of view.controls) control.disabled = busy || isBlocked() || unavailable;
      if (view.retry) view.retry.disabled = busy || isBlocked();
    }
  }
  function renderView(view) {
    const record = recordFor(view.recommendationId), state = record.states.get(view.look.look_id);
    const root = view.node;
    root.replaceChildren(); view.controls = []; view.retry = null;
    const actions = element("div", "look-feedback-actions");
    function button(action, label, selected = false) {
      const node = element("button", "button secondary-button look-interaction-button", label);
      node.type = "button";
      node.dataset.action = action;
      node.dataset.lookId = String(view.look.look_id);
      node.dataset.recommendationId = view.recommendationId;
      node.setAttribute("aria-pressed", String(selected));
      node.setAttribute("aria-label", "LOOK " + view.look.look_id + " " + label);
      node.addEventListener("click", () => { void change(view, action); });
      view.controls.push(node); actions.append(node);
      return node;
    }
    if (!view.savedOnly) {
      button("like", "좋아요", state?.feedback === "like");
      button("dislike", "싫어요", state?.feedback === "dislike");
    }
    const saved = state ? state.saved : view.savedOnly;
    button("save", saved ? "저장 취소" : "코디 저장", saved);
    root.append(actions);
    if (!view.savedOnly && state?.feedback === "dislike") {
      const draft = reasonDraft(record, view.look.look_id, state);
      const label = element("label", "look-feedback-reason", "어떤 점이 아쉬웠나요? (선택)");
      const select = element("select", "look-feedback-select");
      select.dataset.action = "dislike-reason";
      select.dataset.lookId = String(view.look.look_id);
      select.dataset.recommendationId = view.recommendationId;
      select.setAttribute("aria-label", "LOOK " + view.look.look_id + " 싫어요 사유 (선택)");
      const none = element("option", "", "사유 선택 안 함"); none.value = ""; select.append(none);
      for (const [value, title] of Object.entries(FEEDBACK_REASON_LABELS)) {
        const option = element("option", "", title); option.value = value; select.append(option);
      }
      select.value = draft.reason || "";
      select.addEventListener("change", () => {
        if (!views.includes(view) || busy || isBlocked() || record.phase !== "ready") return;
        draft.reason = select.value || null; draft.dirty = true;
        if (draft.reason === "other") {
          notice(record, view.look.look_id, "기타 사유를 입력한 뒤 ‘사유 저장’을 눌러 주세요.");
          renderView(view); refreshControls();
          view.node.querySelector('[data-action="dislike-reason-text"]')?.focus({ preventScroll: true });
        } else void change(view, "reason", draft.reason);
      });
      view.controls.push(select); label.append(select); root.append(label);
      if (draft.reason === "other") {
        const editor = element("div", "look-feedback-editor");
        const textLabel = element("label", "look-feedback-text-label", "기타 사유");
        const textarea = element("textarea", "look-feedback-text");
        const textId = "feedback-text-" + view.recommendationId + "-" + view.look.look_id;
        textarea.id = textId; textLabel.setAttribute("for", textId);
        textarea.dataset.action = "dislike-reason-text";
        textarea.dataset.lookId = String(view.look.look_id);
        textarea.dataset.recommendationId = view.recommendationId;
        textarea.rows = 4;
        // Native maxlength counts UTF-16 units; every valid 300-codepoint string must fit.
        textarea.maxLength = FEEDBACK_TEXT_LIMIT * 2;
        textarea.value = draft.text;
        textarea.placeholder = "예: 오래 걸어야 하는 날이라 더 편한 신발을 원해요.";
        const counter = element("p", "look-feedback-text-count");
        counter.id = textId + "-count";
        textarea.setAttribute("aria-describedby", counter.id);
        function updateCounter() {
          const length = Array.from(draft.text.trim()).length;
          counter.textContent = length + " / " + FEEDBACK_TEXT_LIMIT + "자";
          counter.dataset.kind = length > FEEDBACK_TEXT_LIMIT ? "error" : "info";
          textarea.setAttribute("aria-invalid", String(length > FEEDBACK_TEXT_LIMIT));
        }
        textarea.addEventListener("input", () => {
          draft.text = textarea.value; draft.dirty = true; updateCounter();
        });
        updateCounter();
        const submit = element("button", "button secondary-button look-feedback-text-save", "사유 저장");
        submit.type = "button"; submit.dataset.action = "save-dislike-reason";
        submit.dataset.lookId = String(view.look.look_id);
        submit.dataset.recommendationId = view.recommendationId;
        submit.addEventListener("click", () => { void change(view, "reason", "other", draft.text); });
        view.controls.push(textarea, submit);
        editor.append(textLabel, textarea, counter, submit); root.append(editor);
      }
    }
    const status = element("p", "look-interaction-status");
    status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    view.status = status;
    updateStatus(view, record);
    root.append(status);
    if (record.phase === "error" && (record.errorLookId === null || record.errorLookId === view.look.look_id)) {
      const retry = element("button", "button secondary-button look-interaction-retry", "평가·저장 상태 다시 확인");
      retry.type = "button"; retry.dataset.action = "retry-interactions";
      retry.dataset.lookId = String(view.look.look_id);
      retry.dataset.recommendationId = view.recommendationId;
      retry.addEventListener("click", () => {
        if (views.includes(view)) void load(view.recommendationId, null, view.look.look_id);
      });
      view.retry = retry; root.append(retry);
    }
  }
  function renderViews(recommendationId) {
    for (const view of views) if (!recommendationId || view.recommendationId === recommendationId) renderView(view);
    refreshControls();
  }
  function mount(recommendationId, look, { savedOnly = false } = {}) {
    const node = element("div", "look-interactions");
    if (look.status !== "available") return node;
    const record = recordFor(recommendationId);
    record.expected.set(look.look_id, look);
    const view = { recommendationId, look, savedOnly, node, controls: [], retry: null };
    views.push(view); renderView(view); refreshControls();
    return node;
  }
  function checkStatuses(record, states) {
    for (const state of states) {
      if (record.expected.has(state.look_id) && record.expected.get(state.look_id).status !== state.status) {
        throw new Error("평가·저장 상태가 추천 결과와 일치하지 않습니다.");
      }
    }
  }
  async function readState(context, recommendationId) {
    if (!await verify(context)) return null;
    const response = validateInteractions(await authenticatedRequest(
      "/recommendations/" + recommendationId + "/interactions",
    ), recommendationId);
    if (!context.current()) return null;
    checkStatuses(recordFor(recommendationId), response.looks);
    if (!await verify(context)) return null;
    return response.looks;
  }
  function accept(recommendationId, states, { text = "", kind = "success", lookId = null, clearDraft = false } = {}) {
    const record = recordFor(recommendationId);
    for (const state of states) {
      record.states.set(state.look_id, state);
      if ((clearDraft && state.look_id === lookId) || !record.drafts.get(state.look_id)?.dirty) {
        record.drafts.delete(state.look_id);
      }
    }
    record.phase = "ready"; record.message = ""; record.kind = "info"; record.errorLookId = null;
    if (lookId !== null) notice(record, lookId, text, kind);
    renderViews(recommendationId);
    onChange(states);
  }
  async function load(recommendationId, looks = null, sourceLookId = null) {
    if (busy || isBlocked()) return;
    const context = capture();
    if (!context?.current()) return;
    const record = recordFor(recommendationId);
    if (looks) for (const look of looks) record.expected.set(look.look_id, look);
    record.phase = "loading"; record.errorLookId = sourceLookId;
    record.message = sourceLookId === null ? "평가·저장 상태를 확인하고 있어요." : "";
    record.kind = "info";
    if (sourceLookId === null) clearNotices(record);
    else notice(record, sourceLookId, "평가·저장 상태를 확인하고 있어요.");
    setBusy(true); renderViews(recommendationId);
    try {
      const states = await readState(context, recommendationId);
      if (states && context.current()) accept(recommendationId, states, {
        lookId: sourceLookId, text: sourceLookId === null ? "" : "서버의 평가·저장 상태를 확인했어요.", kind: "info",
      });
    } catch (error) {
      if (!context.current() || expireIfNeeded(context, error)) return;
      record.phase = "error"; record.kind = "error"; record.errorLookId = sourceLookId;
      const text = interactionError(error) + " ‘평가·저장 상태 다시 확인’을 눌러 주세요.";
      if (sourceLookId === null) record.message = text;
      else notice(record, sourceLookId, text, "error");
      renderViews(recommendationId);
    } finally {
      if (context.current()) setBusy(false);
    }
  }
  async function change(view, action, reason = null, reasonText = null) {
    if (!views.includes(view) || busy || isBlocked()) return;
    const record = recordFor(view.recommendationId), state = record.states.get(view.look.look_id);
    if (record.phase !== "ready" && !(view.savedOnly && record.phase === "idle")) return;
    const context = capture();
    if (!context?.current()) return;
    let method, resource, body, success;
    if (action === "save") {
      const saved = state ? state.saved : view.savedOnly;
      method = saved ? "DELETE" : "PUT"; resource = "saved";
      success = saved ? "코디 저장을 취소했어요." : "코디를 저장했어요. 저장한 코디에서 다시 볼 수 있어요.";
    } else {
      if (!state) return;
      resource = "feedback";
      if (action === "reason") {
        if (state.feedback !== "dislike") return;
        try { body = buildFeedbackPayload("dislike", reason, reasonText); }
        catch (error) {
          notice(record, view.look.look_id, interactionError(error), "error");
          renderView(view); refreshControls();
          view.node.querySelector('[data-action="dislike-reason-text"]')?.focus({ preventScroll: true });
          return;
        }
        method = "PUT";
        success = "싫어요 사유를 저장했어요.";
      } else if (action === "like" || action === "dislike") {
        const cancel = state.feedback === action;
        method = cancel ? "DELETE" : "PUT";
        if (!cancel) body = buildFeedbackPayload(action);
        success = cancel ? "평가를 취소했어요." : action === "like" ? "좋아요를 남겼어요." : "싫어요를 남겼어요. 사유는 선택할 수 있어요.";
      } else return;
    }
    notice(record, view.look.look_id, "변경 사항을 저장하고 있어요.");
    setBusy(true); renderViews(view.recommendationId);
    let attempted = false;
    try {
      if (!await verify(context)) return;
      attempted = true;
      const response = validateInteraction(await authenticatedRequest(
        "/recommendations/" + view.recommendationId + "/looks/" + view.look.look_id + "/" + resource,
        { method, ...(body ? { body } : {}) },
      ), view.recommendationId, view.look.look_id);
      if (!context.current()) return;
      checkStatuses(record, [response]);
      if (!await verify(context)) return;
      accept(view.recommendationId, [response], { text: success, lookId: view.look.look_id, clearDraft: resource === "feedback" });
    } catch (error) {
      if (!context.current() || expireIfNeeded(context, error)) return;
      record.phase = "error"; record.errorLookId = view.look.look_id; record.message = "";
      notice(record, view.look.look_id, interactionError(error) + " 평가·저장 상태를 다시 확인해 주세요.", "error");
      renderViews(view.recommendationId);
      // A request can commit even when its response is lost. Never repeat the mutation.
      if (attempted) {
        try {
          const states = await readState(context, view.recommendationId);
          if (states && context.current()) accept(view.recommendationId, states, {
            text: "변경 응답을 확인하지 못해 서버 상태를 다시 불러왔어요. 표시된 선택 상태를 확인해 주세요.",
            kind: "info", lookId: view.look.look_id,
          });
        } catch (readError) {
          if (!context.current() || expireIfNeeded(context, readError)) return;
          record.phase = "error"; record.errorLookId = view.look.look_id; record.message = "";
          notice(record, view.look.look_id, "변경 결과를 확인하지 못했어요. ‘평가·저장 상태 다시 확인’을 먼저 눌러 주세요.", "error");
          renderViews(view.recommendationId);
        }
      }
    } finally {
      if (context.current()) {
        setBusy(false);
        const currentView = views.find(item => item.recommendationId === view.recommendationId && item.look.look_id === view.look.look_id);
        currentView?.controls.find(node => node.dataset.action === (action === "reason" ? "dislike-reason" : action))?.focus({ preventScroll: true });
      }
    }
  }
  return { mount, beginRender, reset, load, refreshControls, isSaving: () => busy };
}
