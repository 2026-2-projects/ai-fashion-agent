const messages = {
  insecure: "HTTPS 또는 localhost에서 실행해 주세요.",
  unsupported: "이 브라우저는 위치 조회를 지원하지 않습니다.",
  denied: "위치 접근이 차단되었습니다. 브라우저·운영체제 권한과 사이트 정책을 확인해 주세요.",
  unavailable: "현재 위치를 확인할 수 없습니다. 위치 서비스를 확인하거나 다시 시도해 주세요.",
  timeout: "위치 조회 시간이 초과되었습니다. 다시 시도해 주세요.",
  invalid: "올바른 위치 데이터를 받지 못했습니다.",
};

export class LocationError extends Error {
  constructor(code) {
    super(messages[code]);
    this.name = "LocationError";
    this.code = code;
  }
}

// Injection allows tests to use synthetic coordinates without device permission.
export function getCurrentLocation(environment = globalThis) {
  return new Promise((resolve, reject) => {
    if (!environment.isSecureContext) {
      reject(new LocationError("insecure"));
      return;
    }
    const geolocation = environment.navigator?.geolocation;
    if (typeof geolocation?.getCurrentPosition !== "function") {
      reject(new LocationError("unsupported"));
      return;
    }
    try {
      geolocation.getCurrentPosition(
        (position) => {
          const { latitude, longitude, accuracy } = position?.coords ?? {};
          const timestamp = position?.timestamp;
          if (
            !Number.isFinite(latitude) || latitude < -90 || latitude > 90 ||
            !Number.isFinite(longitude) || longitude < -180 || longitude > 180 ||
            !Number.isFinite(accuracy) || accuracy < 0 ||
            !Number.isFinite(timestamp) || timestamp < 0 ||
            !Number.isFinite(new Date(timestamp).getTime())
          ) {
            reject(new LocationError("invalid"));
            return;
          }
          resolve({ latitude, longitude, accuracy, capturedAt: new Date(timestamp).toISOString() });
        },
        (error) => reject(new LocationError(
          ({ 1: "denied", 2: "unavailable", 3: "timeout" })[error?.code] ?? "unavailable",
        )),
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 },
      );
    } catch (error) {
      reject(new LocationError(error?.name === "SecurityError" ? "denied" : "unavailable"));
    }
  });
}
