/** CLOMORI clarification preflight: optional high-value questions before 5 LOOK generation.
 * All API decisions are authenticated by the backend. Never persists conversation text.
 * Keeps the original recommendation form listener and API behavior intact.
 */
import { normalize24Hour } from './clomori-v2.js';

const API_ROOT = '/api/v1';
const MAX_FOLLOWUPS = 2;
const CHOICE_ONLY_QUESTIONS = new Set(['place_conflict', 'date_conflict', 'time_conflict']);

function sameRequest(a, b) {
  if (!a || !b) return false;
  return ['message', 'place', 'date', 'time'].every(key => (a[key] || null) === (b[key] || null));
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function readForm(form, { normalizeTime = true } = {}) {
  const messageField = form.querySelector('textarea[name="message"], #recommendation-message, textarea');
  const place = document.getElementById('recommendation-place') || form.querySelector('[name="place"]');
  const date = document.getElementById('recommendation-date') || form.querySelector('[name="date"]');
  const time = document.getElementById('recommendation-time') || form.querySelector('[name="time"]');
  if (time && normalizeTime) {
    const normalized = normalize24Hour(time.value);
    if (normalized !== time.value) time.value = normalized;
  }
  return {
    fields: { messageField, place, date, time },
    payload: {
      message: messageField?.value.trim() || '',
      place: place?.value.trim() || null,
      date: date?.value || null,
      time: time?.value || null,
    },
  };
}

function explainError(error, status) {
  if (status === 401) return '로그인이 필요해요. 다시 로그인한 뒤 요청해 주세요.';
  if (status === 403) return '로그인 세션을 확인하지 못했어요. 새로고침 후 다시 시도해 주세요.';
  if (status === 422) return error || '입력 내용을 확인해 주세요. 날짜·시간 또는 요청 길이가 올바르지 않을 수 있어요.';
  if (status >= 500) return '서버에서 질문을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.';
  return error || '질문을 확인하지 못했어요. 다시 시도해 주세요.';
}

async function apiRequest(path, options = {}, signal) {
  const response = await fetch(API_ROOT + path, {
    ...options,
    credentials: 'same-origin',
    signal,
    headers: { Accept: 'application/json', ...(options.headers || {}) },
  });
  let payload = null;
  try { payload = await response.json(); } catch { /* empty error responses */ }
  if (!response.ok) {
    const message = typeof payload?.detail === 'string' ? payload.detail : null;
    const error = new Error(explainError(message, response.status));
    error.status = response.status;
    throw error;
  }
  return payload;
}

export function mountClarificationUI() {
  const form = document.getElementById('recommendation-form');
  if (!form || form.dataset.cmClarifyMounted === 'true') return;
  form.dataset.cmClarifyMounted = 'true';

  let original = null;
  let answers = [];
  let question = null;
  let ownerId = null;
  let busy = false;
  let bypassNext = false;
  let epoch = 0;
  let controller = null;
  const panel = element('section', 'cm-clarify-panel');
  panel.id = 'cm-clarification';
  panel.hidden = true;
  panel.setAttribute('aria-label', '코디 추천 추가 질문');
  panel.setAttribute('role', 'region');
  const message = element('p', 'cm-clarify-feedback');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  // Keep the follow-up inside the existing left-side form, not as a new grid column.
  form.append(panel, message);

  function reset() {
    epoch += 1;
    controller?.abort();
    controller = null;
    busy = false;
    original = null;
    answers = [];
    question = null;
    ownerId = null;
    bypassNext = false;
    panel.hidden = true;
    panel.replaceChildren();
    message.textContent = '';
  }

  function setMessage(text, isError = false) {
    message.textContent = text;
    message.classList.toggle('is-error', isError);
  }

  function renderQuestion() {
    if (!question) { panel.hidden = true; return; }
    panel.hidden = false;
    panel.replaceChildren();
    // A maximum of two questions does not mean two questions are always necessary.
    const eyebrow = element('p', 'cm-clarify-eyebrow', `CLOMORI · 추가 질문 ${answers.length + 1}`);
    const title = element('h3', 'cm-clarify-title', question.question);
    const guidance = answers.length + 1 >= MAX_FOLLOWUPS
      ? '답변을 반영해 추천해 드릴게요. 원하지 않으면 바로 추천받을 수도 있어요.'
      : '필요할 때만 한 번 더 확인해요. 원하지 않으면 바로 추천받을 수도 있어요.';
    const hint = element('p', 'cm-clarify-hint', guidance);
    const input = document.createElement('input');
    const choiceOnly = CHOICE_ONLY_QUESTIONS.has(question.question_id);
    input.type = choiceOnly ? 'hidden' : 'text';
    input.className = 'cm-clarify-input';
    input.placeholder = question.question_id === 'destination' ? '예: 강릉' : '예: 결혼식';
    input.maxLength = 100;
    input.autocomplete = 'off';
    input.setAttribute('aria-label', '추가 질문 답변');
    const suggestions = element('div', 'cm-clarify-suggestions');
    if (choiceOnly) {
      suggestions.setAttribute('role', 'group');
      suggestions.setAttribute('aria-label', '추가 질문 답변 선택');
    }
    for (const option of (question.suggestions || []).slice(0, 4)) {
      const button = element('button', 'cm-clarify-choice', option);
      button.type = 'button';
      // A selected option must not look like the primary submit action.
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => {
        input.value = option;
        for (const child of suggestions.children) {
          child.setAttribute('aria-pressed', String(child === button));
        }
        if (!choiceOnly) input.focus();
      });
      suggestions.append(button);
    }
    // Typing a custom answer clears stale visual selection of suggestion chips.
    if (!choiceOnly) input.addEventListener('input', () => {
      const typed = input.value.trim();
      for (const child of suggestions.children) {
        child.setAttribute('aria-pressed', String(child.textContent === typed));
      }
    });
    const actions = element('div', 'cm-clarify-actions');
    const send = element('button', 'cm-clarify-send', '답변 보내기');
    send.type = 'button';
    send.addEventListener('click', () => {
      const reply = input.value.trim();
      if (!reply) {
        if (!choiceOnly) input.focus();
        setMessage(choiceOnly ? '입력창과 요청 문장 중 하나를 선택해 주세요.' : '답변을 입력하거나 ‘그냥 추천받기’를 선택해 주세요.', true);
        return;
      }
      if (!original || !question) return;
      if (!sameRequest(original, readForm(form).payload)) {
        reset();
        setMessage('요청이 변경되어 입력 정보를 다시 확인할게요. 추천받기를 다시 눌러 주세요.');
        return;
      }
      const candidate = [...answers, { question_id: question.question_id, answer: reply }];
      void askServer(original, candidate, false);
    });
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.isComposing) {
        event.preventDefault();
        send.click();
      }
    });
    const skip = element('button', 'cm-clarify-skip', '그냥 추천받기');
    skip.type = 'button';
    skip.addEventListener('click', () => {
      if (!original) return;
      if (!sameRequest(original, readForm(form).payload)) {
        reset();
        setMessage('요청이 변경됐어요. 추천받기를 다시 눌러 주세요.');
        return;
      }
      void askServer(original, answers, true);
    });
    const cancel = element('button', 'cm-clarify-cancel', '취소');
    cancel.type = 'button';
    cancel.addEventListener('click', reset);
    actions.append(send, skip, cancel);
    panel.append(eyebrow, title, hint, suggestions, input, actions);
    if (!choiceOnly) input.focus();
  }

  function useRecommendation(resolved) {
    const { fields } = readForm(form);
    if (!fields.messageField) { setMessage('추천 입력창을 찾지 못했어요.', true); return; }
    // Re-use existing submission logic; do not create a second recommendation API call.
    fields.messageField.value = resolved.message;
    if (fields.place && resolved.place !== undefined) fields.place.value = resolved.place || '';
    if (fields.date && resolved.date !== undefined) fields.date.value = resolved.date || '';
    if (fields.time && resolved.time !== undefined) fields.time.value = resolved.time || '';
    original = null;
    answers = [];
    question = null;
    panel.hidden = true;
    panel.replaceChildren();
    setMessage('');
    // The next *synchronous* submit belongs to recommendation.js, not this preflight.
    if (!form.reportValidity()) return;
    bypassNext = true;
    try {
      // Dispatch synchronously to the already installed recommendation.js listener.
      // This avoids an extra native form navigation if the browser suppresses a
      // second requestSubmit during a cancelled submit event.
      const submitter = form.querySelector('button[type="submit"], input[type="submit"]');
      form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true, submitter }));
    } finally { bypassNext = false; }
  }

  async function askServer(payload, candidateAnswers, skip) {
    if (busy) return;
    busy = true;
    const run = ++epoch;
    controller?.abort();
    controller = new AbortController();
    setMessage('입력하신 상황을 확인하는 중이에요.');
    try {
      const auth = await apiRequest('/auth/me', { method: 'GET' }, controller.signal);
      if (run !== epoch) return;
      if (!Number.isInteger(auth.id) || !auth.csrf_token) throw new Error('로그인을 다시 확인해 주세요.');
      if (ownerId !== null && ownerId !== auth.id) {
        reset();
        setMessage('계정이 변경되어 이전 질문을 초기화했어요. 다시 요청해 주세요.', true);
        return;
      }
      ownerId = auth.id;
      const decision = await apiRequest('/agent/clarify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': auth.csrf_token },
        body: JSON.stringify({ ...payload, answers: candidateAnswers, skip }),
      }, controller.signal);
      if (run !== epoch) return;
      if (decision.decision === 'ask') {
        if (!decision.question_id || !decision.question) throw new Error('질문 응답 형식을 확인할 수 없어요.');
        original = payload;
        answers = candidateAnswers;
        question = decision;
        renderQuestion();
        setMessage('');
      } else if (decision.decision === 'ready' && decision.resolved_request) {
        useRecommendation(decision.resolved_request);
      } else {
        throw new Error('서버 응답 형식을 확인할 수 없어요.');
      }
    } catch (error) {
      if (run !== epoch || error?.name === 'AbortError') return;
      setMessage(error instanceof Error ? error.message : '질문 확인에 실패했어요.', true);
    } finally {
      if (run === epoch) { busy = false; controller = null; }
    }
  }

  // Capturing before the pre-existing recommendation.js submit listener keeps its
  // authentication, loading states, snapshot restoration, and 5 LOOK rendering.
  document.addEventListener('submit', function intercept(event) {
    if (event.target !== form) return;
    if (bypassNext) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (busy) return;
    const { fields, payload } = readForm(form);
    if (!fields.messageField || !payload.message) {
      setMessage('어떤 코디가 필요한지 입력해 주세요.', true);
      return;
    }
    if (question && original && sameRequest(original, payload)) {
      renderQuestion();
      setMessage('추가 질문에 답하거나 ‘그냥 추천받기’를 선택해 주세요.');
      return;
    }
    original = payload;
    answers = [];
    question = null;
    panel.hidden = true;
    void askServer(original, [], false);
  }, true);

  // An edited form field invalidates questions derived from the earlier values.
  // This also aborts a request in flight rather than applying a stale reply.
  const relevantIds = new Set([
    'recommendation-message', 'recommendation-place', 'recommendation-date', 'recommendation-time',
  ]);
  function invalidateOnEdit(event) {
    if (!original) return;
    const live = readForm(form, { normalizeTime: false });
    if (!relevantIds.has(event.target?.id) && ![
      live.fields.messageField, live.fields.place, live.fields.date, live.fields.time,
    ].includes(event.target)) return;
    if (sameRequest(original, live.payload)) return;
    reset();
    setMessage('입력 정보가 변경됐어요. 새 내용으로 추천받기를 눌러 주세요.');
  }
  form.addEventListener('input', invalidateOnEdit);
  form.addEventListener('change', invalidateOnEdit);

  // Do not expose a previous user's pending answers after leaving the protected page.
  window.addEventListener('hashchange', () => {
    if (location.hash !== '#recommendation') reset();
  });
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountClarificationUI, { once: true });
  else mountClarificationUI();
}
