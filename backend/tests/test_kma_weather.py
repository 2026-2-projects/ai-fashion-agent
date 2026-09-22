from datetime import date, datetime

import httpx
import pytest

from app import weather_cli
from app.services.kma_weather import KST, KmaWeatherClient, WeatherError, latest_base, to_grid

NOW = datetime(2026, 9, 22, 10, tzinfo=KST)
DAY = date(2026, 9, 23)
KEY = "test+secret/key="


def item(category="TMP", value="23.5", time="0900", day="20260923"):
    return {
        "baseDate": "20260922",
        "baseTime": "0800",
        "nx": 60,
        "ny": 127,
        "fcstDate": day,
        "fcstTime": time,
        "category": category,
        "fcstValue": value,
    }


def payload(items=None, *, total=None, page=1):
    items = [item()] if items is None else items
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "OK"},
            "body": {
                "totalCount": len(items) if total is None else total,
                "pageNo": page,
                "items": {"item": items},
            },
        }
    }


def query(handler, key=KEY, day=DAY):
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        return KmaWeatherClient(http, key).get_forecast(37.5665, 126.978, day, now=NOW)


@pytest.mark.parametrize(
    "lat,lon,expected",
    [
        (38, 126, (43, 136)),
        (37.5665, 126.978, (60, 127)),
        (35.1796, 129.0756, (98, 76)),
        (33.4996, 126.5312, (53, 38)),
    ],
)
def test_grid(lat, lon, expected):
    assert to_grid(lat, lon) == expected


@pytest.mark.parametrize(
    "lat,lon",
    [
        (float("nan"), 127),
        (37, float("inf")),
        (90, 127),
        (-90, 127),
        (127, 37),
        (0, 0),
        (37, 181),
    ],
)
def test_invalid_grid(lat, lon):
    with pytest.raises(WeatherError):
        to_grid(lat, lon)


@pytest.mark.parametrize(
    "now,expected",
    [
        ("2026-09-22T00:30:00+09:00", "2026-09-21T23:00:00+09:00"),
        ("2026-09-22T02:59:00+09:00", "2026-09-21T23:00:00+09:00"),
        ("2026-09-22T03:00:00+09:00", "2026-09-22T02:00:00+09:00"),
        ("2026-09-21T18:00:00+00:00", "2026-09-22T02:00:00+09:00"),
        ("2026-01-01T00:00:00+09:00", "2025-12-31T23:00:00+09:00"),
    ],
)
def test_base_time(now, expected):
    assert latest_base(datetime.fromisoformat(now)).isoformat() == expected


def test_naive_time():
    with pytest.raises(WeatherError, match="시간대"):
        latest_base(datetime(2026, 9, 22))


def test_request_and_normalization():
    def handler(request):
        assert request.url.scheme == "https"
        assert request.url.host == "apis.data.go.kr"
        assert request.url.path.endswith("/getVilageFcst")
        assert dict(request.url.params) == {
            "serviceKey": KEY,
            "dataType": "JSON",
            "pageNo": "1",
            "numOfRows": "1000",
            "base_date": "20260922",
            "base_time": "0800",
            "nx": "60",
            "ny": "127",
        }
        assert request.extensions["timeout"]["read"] == 10
        return httpx.Response(
            200,
            json=payload(
                [
                    item(),
                    item("POP", "60"),
                    item("PTY", "1"),
                    item("WSD", "2.1"),
                    item("REH", "80"),
                    item("SKY", "4"),
                    item("PCP", "1.0~29.9mm"),
                    item("TMN", "15"),
                    item(time="1000"),
                    item(day="20260924"),
                ]
            ),
        )

    result = query(handler)
    assert result["source"] == "기상청"
    assert result["base_at"] == "2026-09-22T08:00:00+09:00"
    assert result["date"] == "2026-09-23"
    assert result["forecasts"][0] == {
        "forecast_at": "2026-09-23T09:00:00+09:00",
        "temperature_c": 23.5,
        "precipitation_probability_pct": 60,
        "precipitation_type_code": 1,
        "wind_speed_m_s": 2.1,
        "humidity_pct": 80,
        "sky_code": 4,
        "precipitation": "1.0~29.9mm",
    }
    assert len(result["forecasts"]) == 2
    assert result["forecasts"][1]["humidity_pct"] is None
    assert "latitude" not in str(result)
    assert KEY not in str(result)


def test_pagination_merges_categories_and_sorts():
    calls = []

    def handler(request):
        page = int(request.url.params["pageNo"])
        calls.append(page)
        rows = [item(time="1000")] if page == 1 else [item(), item("POP", "0")]
        return httpx.Response(200, json=payload(rows, total=3, page=page))

    result = query(handler)
    assert calls == [1, 2]
    assert result["forecasts"][0]["precipitation_probability_pct"] == 0


@pytest.mark.parametrize(
    "code,match",
    [
        ("20", "인증"),
        ("30", "인증"),
        ("31", "인증"),
        ("22", "한도"),
        ("23", "한도"),
        ("03", "자료가 없습니다"),
        ("99", "오류"),
    ],
)
@pytest.mark.parametrize("xml", [False, True])
def test_api_errors_are_safe(code, match, xml):
    def handler(request):
        if xml:
            return httpx.Response(
                200,
                text=(
                    f"<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>{KEY}</returnAuthMsg>"
                    f"<returnReasonCode>{code}</returnReasonCode>"
                    "</cmmMsgHeader></OpenAPI_ServiceResponse>"
                ),
            )
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {
                        "resultCode": code,
                        "resultMsg": KEY,
                    }
                }
            },
        )

    with pytest.raises(WeatherError, match=match) as exc:
        query(handler)
    assert KEY not in str(exc.value)


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_http_errors(status):
    with pytest.raises(WeatherError) as exc:
        query(lambda request: httpx.Response(status, text=KEY))
    assert KEY not in str(exc.value)


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_network_errors(error):
    def handler(request):
        raise error(str(request.url), request=request)

    with pytest.raises(WeatherError) as exc:
        query(handler)
    assert KEY not in str(exc.value)
    assert "serviceKey" not in str(exc.value)


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        {"response": None},
        payload([item(value="NaN")]),
        payload([item("POP", "101")]),
        payload([item("WSD", "-1")]),
        payload([item("SKY", "2")]),
        payload([item(time="2500")]),
        payload([item(), item()]),
        payload([], total=2),
        payload(total=20001),
        payload(page=2),
        payload([dict(item(), nx=1)]),
    ],
)
def test_malformed_data(data):
    with pytest.raises(WeatherError):
        query(lambda request: httpx.Response(200, json=data))


def test_non_json():
    with pytest.raises(WeatherError, match="형식"):
        query(lambda request: httpx.Response(200, text="<html>bad gateway</html>"))


@pytest.mark.parametrize("mode", ["repeated", "changed_total", "empty"])
def test_broken_pagination(mode):
    def handler(request):
        page = int(request.url.params["pageNo"])
        rows = [item()]
        total = 3
        if page == 2:
            if mode == "changed_total":
                total = 4
                rows = [item(time="1000")]
            elif mode == "empty":
                rows = []
        return httpx.Response(200, json=payload(rows, total=total, page=page))

    with pytest.raises(WeatherError, match="페이지"):
        query(handler)


def test_near_pole_is_safe_error():
    with pytest.raises(WeatherError):
        to_grid(-89.99999999999999, 127)


@pytest.mark.parametrize("rows", [[], [item(day="20260924")]])
def test_no_matching_forecast(rows):
    with pytest.raises(WeatherError, match="예보가 없습니다"):
        query(lambda request: httpx.Response(200, json=payload(rows)))


def test_missing_value_not_invented():
    result = query(lambda request: httpx.Response(200, json=payload([item(value="-999")])))
    assert result["forecasts"][0]["temperature_c"] is None


@pytest.mark.parametrize("key,day", [("", DAY), ("encoded%2Bkey", DAY), (KEY, date(2020, 1, 1))])
def test_invalid_request_does_not_call_api(key, day):
    def handler(request):
        pytest.fail("invalid request must not reach API")

    with pytest.raises(WeatherError):
        query(handler, key=key, day=day)


def test_cli_missing_key(monkeypatch, capsys):
    monkeypatch.delenv("KMA_SERVICE_KEY", raising=False)
    assert weather_cli.main(["2099-01-01", "--lat", "37.5", "--lon", "127"]) == 1
    captured = capsys.readouterr()
    assert "KMA_SERVICE_KEY" in captured.err
    assert captured.out == ""


def test_cli_success(monkeypatch, capsys):
    monkeypatch.setattr(KmaWeatherClient, "get_forecast", lambda *a, **kw: {"forecasts": []})
    assert weather_cli.main(["2026-09-23", "--lat", "37.5", "--lon", "127"]) == 0
    assert '"forecasts": []' in capsys.readouterr().out


def test_cli_invalid_date():
    with pytest.raises(SystemExit) as exc:
        weather_cli.main(["not-a-date", "--lat", "37.5", "--lon", "127"])
    assert exc.value.code == 2
