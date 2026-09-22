import { getCurrentLocation, LocationError } from "./geolocation.js";

export function setupLocationPage(root, requestLocation = getCurrentLocation) {
  const request = root.querySelector("[data-request]");
  const clear = root.querySelector("[data-clear]");
  const status = root.querySelector("[data-status]");
  const result = root.querySelector("[data-result]");
  let generation = 0;
  let pending = false;

  function erase() {
    result.hidden = true;
    result.textContent = "";
  }

  function reset() {
    generation += 1;
    pending = false;
    request.disabled = false;
    erase();
    status.textContent = "위치 정보를 지웠습니다. 다시 조회할 수 있습니다.";
  }

  async function locate() {
    if (pending) return;
    const current = ++generation;
    pending = true;
    request.disabled = true;
    erase();
    status.textContent = "위치 확인 중입니다. 권한 안내를 확인해 주세요. 지우기로 대기를 종료할 수 있습니다.";
    try {
      const location = await requestLocation();
      if (current !== generation) return;
      result.textContent = JSON.stringify(location, null, 2);
      result.hidden = false;
      status.textContent = "위치 조회 성공. 아래 좌표는 이 화면에만 표시되며 서버로 전송하지 않습니다.";
    } catch (error) {
      if (current !== generation) return;
      status.textContent = error instanceof LocationError
        ? error.message
        : "위치 조회에 실패했습니다. 다시 시도해 주세요.";
    } finally {
      if (current === generation) {
        pending = false;
        request.disabled = false;
      }
    }
  }

  request.addEventListener("click", locate);
  clear.addEventListener("click", reset);
  const view = root.ownerDocument.defaultView;
  view.addEventListener("pagehide", reset);
  return () => {
    reset();
    request.removeEventListener("click", locate);
    clear.removeEventListener("click", reset);
    view.removeEventListener("pagehide", reset);
  };
}
