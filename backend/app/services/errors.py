"""Location/Weather 도메인에서 API 계층까지 전달하는 안전한 오류."""


class WeatherToolError(Exception):
    """Location/Weather 처리의 기본 오류."""


class WeatherInputError(WeatherToolError):
    """날짜, 시간 또는 장소 입력이 유효하지 않음."""


class ServiceConfigurationError(WeatherToolError):
    """외부 서비스 환경변수가 준비되지 않음."""


class PlaceNotFoundError(WeatherToolError):
    """검색어에 해당하는 장소가 없음."""


class AmbiguousPlaceError(WeatherToolError):
    """장소를 하나로 안전하게 결정할 수 없음."""

    def __init__(self, candidates: list[dict[str, str]]) -> None:
        super().__init__("동일하거나 유사한 장소가 여러 개 검색되었습니다.")
        self.candidates = candidates


class ExternalServiceError(WeatherToolError):
    """Kakao 또는 기상청 외부 서비스 호출/응답 오류."""


class ForecastUnavailableError(WeatherToolError):
    """요청 시각에 사용할 수 있는 단기예보가 없음."""
