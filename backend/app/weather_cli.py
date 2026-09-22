"""Manual verification: python -m app.weather_cli YYYY-MM-DD --lat ... --lon ..."""

import argparse
import json
import os
import sys
from datetime import date

import httpx

from app.services.kma_weather import KmaWeatherClient, WeatherError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="기상청 날짜별 단기예보 조회 (KST)")
    parser.add_argument("date", type=date.fromisoformat)
    parser.add_argument("--lat", type=float, required=True, help="위도 (Kakao y)")
    parser.add_argument("--lon", type=float, required=True, help="경도 (Kakao x)")
    args = parser.parse_args(argv)
    try:
        with httpx.Client() as http:
            result = KmaWeatherClient(http, os.environ.get("KMA_SERVICE_KEY", "")).get_forecast(
                args.lat, args.lon, args.date
            )
    except WeatherError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
