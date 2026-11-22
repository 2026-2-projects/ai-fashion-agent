/** Shared transient success notices and an accessible login password visibility toggle.
 * No network, storage, or authentication logic is changed by this module.
 */

export const SUCCESS_NOTICE_MS = 3000;

const EYE_ICON = `
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
       fill="none" stroke="currentColor" stroke-width="1.7"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/>
    <circle cx="12" cy="12" r="2.8"/>
  </svg>`;
const EYE_OFF_ICON = `
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
       fill="none" stroke="currentColor" stroke-width="1.7"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path d="m3 3 18 18"/>
    <path d="M10.6 6.1A10.7 10.7 0 0 1 12 6c6.5 0 10 6 10 6a15.5 15.5 0 0 1-3.2 3.6"/>
    <path d="M6.6 6.7C3.6 8.5 2 12 2 12s3.5 6 10 6c1.2 0 2.3-.2 3.3-.5"/>
    <path d="M10.3 10.4a2.8 2.8 0 0 0 3.3 3.3"/>
  </svg>`;

/**
 * Attach a 3-second timeout to every actual green success *message*.
 * Persistent green UI state, such as a connected-account badge, isn't a message.
 * New messages reset their own timer; errors and informational messages remain.
 */
export function installSuccessNoticeTimers(root = document, {
  delay = SUCCESS_NOTICE_MS,
  observe = MutationObserver,
  schedule = setTimeout,
  cancel = clearTimeout,
} = {}) {
  const MESSAGE_SELECTOR = '.form-message, .look-interaction-status';
  const active = new WeakMap();

  function sync(element) {
    if (!element?.matches?.(MESSAGE_SELECTOR)) return;
    const previous = active.get(element);
    if (previous) cancel(previous.timer);
    active.delete(element);

    if (element.dataset.kind !== 'success' || !element.textContent?.trim() || !element.isConnected) return;
    const snapshot = element.textContent;
    const entry = { timer: null };
    active.set(element, entry);
    entry.timer = schedule(() => {
      if (active.get(element) !== entry) return;
      active.delete(element);
      if (element.isConnected && element.dataset.kind === 'success' && element.textContent === snapshot) {
        // Removing only the message text avoids resetting forms, caret or selected buttons.
        element.textContent = '';
      }
    }, delay);
  }

  // The observer processes only messages affected by a mutation, not the whole page.
  const observer = new observe((changes) => {
    const candidates = new Set();
    for (const change of changes) {
      const node = change.target;
      const element = node.nodeType === 1 ? node : node.parentElement;
      const owner = element?.closest?.(MESSAGE_SELECTOR);
      if (owner) candidates.add(owner);
      if (change.type === 'childList') {
        for (const added of change.addedNodes) {
          if (added.nodeType !== 1) continue;
          if (added.matches?.(MESSAGE_SELECTOR)) candidates.add(added);
          for (const child of added.querySelectorAll?.(MESSAGE_SELECTOR) || []) candidates.add(child);
        }
      }
    }
    for (const item of candidates) sync(item);
  });
  observer.observe(root.body || root, {
    childList: true, characterData: true, attributes: true,
    attributeFilter: ['data-kind'], subtree: true,
  });
  for (const item of root.querySelectorAll(MESSAGE_SELECTOR)) sync(item);
  return () => observer.disconnect();
}

/** Add a discreet eye/eye-off button to login only. */
export function installLoginPasswordToggle(root = document) {
  const input = root.querySelector('#login-password');
  const form = root.querySelector('#login-form');
  if (!input || !form) return null;
  if (input.parentElement?.classList?.contains('password-field')) {
    return input.parentElement.querySelector('.password-visibility-toggle');
  }
  const wrapper = root.createElement('div');
  wrapper.className = 'password-field';
  const button = root.createElement('button');
  button.type = 'button';
  button.className = 'password-visibility-toggle';
  button.setAttribute('aria-controls', input.id);
  button.setAttribute('aria-pressed', 'false');
  const setVisible = (visible) => {
    input.type = visible ? 'text' : 'password';
    button.setAttribute('aria-pressed', String(visible));
    const name = visible ? '비밀번호 숨기기' : '비밀번호 보기';
    button.setAttribute('aria-label', name);
    button.title = name;
    button.innerHTML = visible ? EYE_OFF_ICON : EYE_ICON;
  };
  setVisible(false);
  input.before(wrapper);
  wrapper.append(input, button);

  button.addEventListener('click', () => setVisible(input.type === 'password'));
  // Hide before the app's submit handler, without clearing the submitted password.
  form.addEventListener('submit', () => setVisible(false), { capture: true });
  // The existing app clears password-type inputs on navigation; restore the type first.
  window.addEventListener('hashchange', () => {
    setVisible(false);
    input.value = '';
  });
  return button;
}

function start() {
  installSuccessNoticeTimers();
  installLoginPasswordToggle();
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
}
