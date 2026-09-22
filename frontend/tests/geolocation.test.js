import { getCurrentLocation, LocationError } from "../js/geolocation.js";
import { setupLocationPage } from "../js/location-page.js";

const tests = [];
const test = (name, run) => tests.push({ name, run });
function assert(condition, message = "assertion failed") {
  if (!condition) throw new Error(message);
}
const position = { coords: { latitude: 37.5, longitude: 127, accuracy: 50 }, timestamp: 1700000000000 };
const environment = (callback) => ({
  isSecureContext: true, navigator: { geolocation: { getCurrentPosition: callback } },
});
async function rejects(promise, code) {
  try { await promise; } catch (error) {
    assert(error instanceof LocationError && error.code === code);
    return;
  }
  throw new Error("expected rejection");
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test("성공: 필요한 필드와 요청 옵션만 사용", async () => {
  const result = await getCurrentLocation(environment((success, failure, options) => {
    assert(options.timeout === 10000 && options.maximumAge === 0 && !options.enableHighAccuracy);
    success({ ...position, coords: { ...position.coords, altitude: 999, speed: 2 } });
  }));
  assert(JSON.stringify(result) === JSON.stringify({
    latitude: 37.5, longitude: 127, accuracy: 50, capturedAt: "2023-11-14T22:13:20.000Z",
  }));
});
test("안전하지 않은 환경: API를 호출하지 않음", async () => {
  await rejects(getCurrentLocation({ isSecureContext: false }), "insecure");
});
test("미지원 브라우저", async () => {
  await rejects(getCurrentLocation({ isSecureContext: true, navigator: {} }), "unsupported");
});
for (const [code, expected] of [[1, "denied"], [2, "unavailable"], [3, "timeout"], [99, "unavailable"]]) {
  test(`브라우저 오류 ${code}: 안전한 오류로 변환`, async () => {
    await rejects(getCurrentLocation(environment((ok, fail) => fail({ code, message: "private" }))), expected);
  });
}
for (const [name, expected] of [["SecurityError", "denied"], ["Error", "unavailable"]]) {
  test(`동기 예외 ${name}`, async () => {
    await rejects(getCurrentLocation(environment(() => { throw { name }; })), expected);
  });
}
for (const coords of [
  { latitude: NaN }, { latitude: 91 }, { longitude: -181 }, { accuracy: -1 },
  { accuracy: Infinity }, { latitude: "37.5" },
]) {
  test(`잘못된 좌표 ${JSON.stringify(coords)}`, async () => {
    await rejects(getCurrentLocation(environment((ok) => ok({
      ...position, coords: { ...position.coords, ...coords },
    }))), "invalid");
  });
}
test("잘못된 시각", async () => {
  await rejects(getCurrentLocation(environment((ok) => ok({ ...position, timestamp: 1e20 }))), "invalid");
});
test("좌표 없는 응답", async () => {
  await rejects(getCurrentLocation(environment((ok) => ok(null))), "invalid");
});

function mount(provider) {
  const root = document.querySelector("#fixture");
  root.innerHTML = '<button data-request>조회</button><button data-clear>지우기</button><p data-status></p><pre data-result hidden></pre>';
  const dispose = setupLocationPage(root, provider);
  return { root, dispose, request: root.querySelector("[data-request]"),
    clear: root.querySelector("[data-clear]"), result: root.querySelector("[data-result]"),
    status: root.querySelector("[data-status]") };
}
test("UI: 자동 요청 없음·중복 클릭 방지·성공·지우기", async () => {
  let calls = 0;
  let finish;
  const ui = mount(() => { calls++; return new Promise((resolve) => { finish = resolve; }); });
  try {
    assert(calls === 0);
    ui.request.click(); ui.request.click();
    assert(calls === 1 && ui.request.disabled);
    finish({ latitude: 37.5 }); await flush();
    assert(!ui.result.hidden && !ui.request.disabled);
    ui.clear.click();
    assert(ui.result.hidden && ui.result.textContent === "");
  } finally { ui.dispose(); }
});
test("UI: 대기 종료 후 늦은 응답 무시", async () => {
  let finish;
  const ui = mount(() => new Promise((resolve) => { finish = resolve; }));
  try {
    ui.request.click(); ui.clear.click(); finish({ latitude: 37.5 }); await flush();
    assert(ui.result.hidden && ui.result.textContent === "" && !ui.request.disabled);
  } finally { ui.dispose(); }
});
test("UI: 이전 요청이 새 요청 결과를 덮어쓰지 않음", async () => {
  const callbacks = [];
  const ui = mount(() => new Promise((resolve) => callbacks.push(resolve)));
  try {
    ui.request.click(); ui.clear.click(); ui.request.click();
    callbacks[1]({ latitude: 35 }); await flush();
    callbacks[0]({ latitude: 37 }); await flush();
    assert(ui.result.textContent.includes("35") && !ui.result.textContent.includes("37"));
  } finally { ui.dispose(); }
});
test("UI: 재조회 실패 시 이전 좌표 삭제·재시도 가능", async () => {
  let calls = 0;
  const ui = mount(async () => {
    if (++calls === 1) return { latitude: 37.5 };
    throw new LocationError("denied");
  });
  try {
    ui.request.click(); await flush(); ui.request.click(); await flush();
    assert(ui.result.hidden && ui.result.textContent === "" && !ui.request.disabled);
    assert(ui.status.textContent.includes("차단"));
  } finally { ui.dispose(); }
});
test("UI: 알 수 없는 오류 원문 비노출", async () => {
  const ui = mount(async () => { throw new Error("private"); });
  try {
    ui.request.click(); await flush(); assert(!ui.status.textContent.includes("private"));
  } finally { ui.dispose(); }
});
test("UI: 페이지 이탈 시 좌표 삭제", async () => {
  const ui = mount(async () => ({ latitude: 37.5 }));
  try {
    ui.request.click(); await flush(); window.dispatchEvent(new Event("pagehide"));
    assert(ui.result.hidden && ui.result.textContent === "");
  } finally { ui.dispose(); }
});

let failed = 0;
const lines = [];
for (const { name, run } of tests) {
  try { await run(); lines.push(`PASS ${name}`); }
  catch (error) { failed++; lines.push(`FAIL ${name}: ${error.message}`); }
}
document.querySelector("#results").textContent = `${tests.length - failed}/${tests.length} passed\n${lines.join("\n")}`;
document.title = failed ? "FAIL — Geolocation tests" : "PASS — Geolocation tests";
