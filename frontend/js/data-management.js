import { authenticatedRequest, finalizeAccountDeletion, getCurrentUser, refreshSession } from "./auth.js";
import { clearRecommendationSnapshots } from "./recommendation-snapshot.js";
// CLOMORI_RECOMMENDATION_FIXES_V3

const NAMES = {
  profile: "프로필", preferences: "패션 취향", wardrobe: "옷장",
  feedback: "평가 기록", saved: "저장한 코디", history: "추천·평가·저장 기록 전체",
};
const COUNT_FIELDS = ["profile", "preferences", "wardrobe", "feedback", "saved", "recommendations"];

/** Account-specific destructive actions are deliberately outside the settings controllers. */
export function createDataManagementController({ navigate, onAccountDeleted, onDataCleared, onSessionExpired, isBlocked }) {
  const summaryEl = document.querySelector("#data-summary");
  const messageEl = document.querySelector("#data-message");
  const accountMessage = document.querySelector("#delete-account-message");
  const deleteForm = document.querySelector("#data-delete-form");
  const deleteFieldset = document.querySelector("#data-delete-fields");
  const accountForm = document.querySelector("#delete-account-form");
  const accountFieldset = document.querySelector("#delete-account-fields");
  const refreshButton = document.querySelector("#data-refresh");
  let epoch = 0;
  let loading = false;
  let busy = false;
  let lastSummary = null;
  let ownerId = null;

  function message(node, text = "", kind = "info") {
    node.textContent = text;
    node.dataset.kind = kind;
  }
  function current(expectedEpoch = epoch) {
    return expectedEpoch === epoch && getCurrentUser()?.id === ownerId && ownerId != null;
  }
  function reset() {
    epoch++;
    ownerId = null;
    busy = false;
    loading = false;
    lastSummary = null;
    deleteForm.reset();
    accountForm.reset();
    message(messageEl);
    message(accountMessage);
    summaryEl.textContent = "";
    refreshControls();
  }
  function isSaving() { return busy; }
  function refreshControls() {
    const disabled = busy || loading || isBlocked() || !lastSummary || !current();
    deleteFieldset.disabled = disabled;
    accountFieldset.disabled = busy || loading || isBlocked() || !current();
    refreshButton.disabled = busy || loading || isBlocked() || !current();
    deleteForm.setAttribute("aria-busy", String(busy));
    accountForm.setAttribute("aria-busy", String(busy));
  }
  function renderSummary(summary) {
    summaryEl.replaceChildren();
    const table = document.createElement("dl");
    table.className = "data-summary-grid";
    const labels = {
      profile: "프로필", preferences: "패션 취향", wardrobe: "옷장 의류",
      feedback: "평가", saved: "저장한 코디", recommendations: "추천 실행 기록",
    };
    for (const key of COUNT_FIELDS) {
      const dt = document.createElement("dt"); dt.textContent = labels[key];
      const dd = document.createElement("dd"); dd.textContent = String(summary[key]);
      table.append(dt, dd);
    }
    summaryEl.append(table);
  }
  function validateSummary(result) {
    if (!result || COUNT_FIELDS.some((key) => !Number.isSafeInteger(result[key]) || result[key] < 0)) {
      throw new Error("데이터 수량 응답을 확인하지 못했습니다.");
    }
    return result;
  }
  async function loadSummary({ keepNotice = false } = {}) {
    const version = epoch;
    if (!current(version) || loading || busy) return;
    loading = true;
    if (!keepNotice) message(messageEl, "내 데이터 수량을 확인하고 있어요.");
    refreshControls();
    try {
      const summary = validateSummary(await authenticatedRequest("/account/data/summary"));
      if (!current(version)) return;
      lastSummary = summary;
      renderSummary(summary);
      if (!keepNotice) message(messageEl);
    } catch (error) {
      if (!current(version)) return;
      lastSummary = null;
      summaryEl.textContent = "불러오기 실패";
      message(messageEl, error.status === 404
        ? "백엔드에 데이터 관리 API가 없습니다. 제공한 백엔드 패치를 먼저 적용해 주세요."
        : error.message, "error");
      if (error.status === 401) onSessionExpired();
    } finally {
      if (version === epoch) {
        loading = false;
        refreshControls();
      }
    }
  }
  function open() {
    reset();
    ownerId = getCurrentUser()?.id ?? null;
    refreshControls();
    void loadSummary();
  }
  refreshButton.addEventListener("click", () => void loadSummary());

  async function revalidateOwner(expectedId) {
    const fresh = await refreshSession();
    if (!fresh || fresh.id !== expectedId || getCurrentUser()?.id !== expectedId) {
      throw new Error("로그인 계정이 변경되었습니다. 다시 확인해 주세요.");
    }
  }
  deleteForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || loading || isBlocked() || !lastSummary || !current()) return;
    const scope = deleteForm.querySelector('input[name="data-scope"]:checked')?.value;
    const passwordInput = document.querySelector("#data-password");
    const confirmationInput = document.querySelector("#data-confirm");
    if (!Object.hasOwn(NAMES, scope)) {
      message(messageEl, "삭제할 데이터 종류를 선택해 주세요.", "error"); return;
    }
    if (confirmationInput.value.trim() !== "삭제") {
      message(messageEl, "확인란에 '삭제'를 정확히 입력해 주세요.", "error"); return;
    }
    if (!passwordInput.value) {
      message(messageEl, "현재 계정의 비밀번호를 입력해 주세요.", "error"); return;
    }
    const version = epoch, expectedId = ownerId;
    busy = true; refreshControls();
    message(messageEl, "요청을 처리하고 있어요. 창을 닫지 마세요.", "info");
    try {
      await revalidateOwner(expectedId);
      if (!current(version)) return;
      const result = await authenticatedRequest("/account/data", {
        method: "DELETE", body: { scope, password: passwordInput.value }, timeoutMs: 30000,
      });
      if (!current(version)) return;
      const summary = validateSummary(result?.summary);
      lastSummary = summary;
      renderSummary(summary);
      const count = Number.isSafeInteger(result?.removed_records) ? result.removed_records : 0;
      if (result?.image_cleanup_failed) {
        message(messageEl,
          `${NAMES[scope]} ${count}건의 DB 기록을 삭제했지만 이미지 파일 ${result.image_cleanup_failed}개의 정리에 실패했습니다. 관리자에게 문의해 주세요.`, "error");
      } else {
        message(messageEl, `${NAMES[scope]} ${count}건을 삭제했어요. 현재 계정은 유지됩니다.`, "success");
      }
      clearRecommendationSnapshots();
      onDataCleared(scope);
      deleteForm.reset();
    } catch (error) {
      if (!current(version)) return;
      message(messageEl, error.message || "삭제 요청에 실패했습니다.", "error");
      if (error.status === 401) onSessionExpired();
    } finally {
      passwordInput.value = "";
      if (version === epoch) { busy = false; refreshControls(); }
    }
  });

  accountForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || loading || isBlocked() || !current()) return;
    const passwordInput = document.querySelector("#delete-account-password");
    const confirmation = document.querySelector("#delete-account-confirm");
    const agreed = document.querySelector("#delete-account-agree");
    if (confirmation.value.trim() !== "회원탈퇴" || !agreed.checked) {
      message(accountMessage, "'회원탈퇴'를 입력하고 삭제 안내에 동의해 주세요.", "error"); return;
    }
    if (!passwordInput.value) {
      message(accountMessage, "현재 계정의 비밀번호를 입력해 주세요.", "error"); return;
    }
    const expectedId = ownerId, version = epoch;
    busy = true; refreshControls();
    message(accountMessage, "계정을 삭제하는 중입니다. 창을 닫지 마세요.", "info");
    try {
      await revalidateOwner(expectedId);
      if (!current(version)) return;
      await authenticatedRequest("/auth/account", {
        method: "DELETE", body: { password: passwordInput.value }, timeoutMs: 30000,
      });
      if (getCurrentUser()?.id !== expectedId) return;
      if (!finalizeAccountDeletion(expectedId)) return;
      clearRecommendationSnapshots();
      onAccountDeleted();
    } catch (error) {
      if (!current(version)) return;
      message(accountMessage, error.message || "회원 탈퇴 요청에 실패했습니다.", "error");
      if (error.status === 401) onSessionExpired();
    } finally {
      passwordInput.value = "";
      if (version === epoch) { busy = false; refreshControls(); }
    }
  });
  return { open, reset, refreshControls, isSaving };
}
