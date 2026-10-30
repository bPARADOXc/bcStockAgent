import json
from unittest.mock import MagicMock

import pytest

from tradingagents.dataflows import a_stock_data_provider as provider_mod
from tradingagents.dataflows.a_stock_data_provider import AStockDataProvider
from tradingagents.dataflows.ashare_provider import ProviderEnvelope
from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.interface import route_to_vendor


class _FakeUrlOpenResponse:
    def __init__(self, text: str):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._text.encode("gbk")


class _FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload or {}
        self.text = text
        self.status_code = 200
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self.content = b"ok"

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


@pytest.mark.unit
def test_tencent_quote_parser_maps_key_fields(monkeypatch):
    vals = [""] * 60
    vals[1] = "贵州茅台"
    vals[3] = "1688.00"
    vals[4] = "1660.00"
    vals[5] = "1668.00"
    vals[31] = "28.00"
    vals[32] = "1.69"
    vals[33] = "1699.00"
    vals[34] = "1650.00"
    vals[37] = "123456"
    vals[38] = "0.88"
    vals[39] = "25.5"
    vals[43] = "2.95"
    vals[44] = "21100"
    vals[45] = "21200"
    vals[46] = "9.8"
    vals[47] = "1826.00"
    vals[48] = "1494.00"
    vals[49] = "1.2"
    vals[52] = "26.0"
    body = 'v_sh600519="' + "~".join(vals) + '";'

    monkeypatch.setattr(provider_mod.urllib.request, "urlopen", lambda req, timeout=10: _FakeUrlOpenResponse(body))

    quote = AStockDataProvider().tencent_quote(["600519"])["600519"]

    assert quote["name"] == "贵州茅台"
    assert quote["price"] == 1688.0
    assert quote["pe_ttm"] == 25.5
    assert quote["pb"] == 9.8
    assert quote["mcap_yi"] == 21200.0
    assert quote["float_mcap_yi"] == 21100.0
    assert quote["limit_up"] == 1826.0
    assert quote["limit_down"] == 1494.0


@pytest.mark.unit
def test_route_to_vendor_dispatches_a_stock_data_and_serializes(monkeypatch):
    cfg = DEFAULT_CONFIG.copy()
    cfg["market"] = {"default_market": "CN_A_SHARE"}
    cfg["tool_vendors"] = {"get_stock_data": "a_stock_data"}
    cfg["provider_fallback_enabled"] = False
    set_config(cfg)

    def fake_stock_data(symbol, start_date, end_date):
        assert symbol == "600519.SH"
        return "# A-Share Stock Data\nDate,Close\n2026-01-02,10\n"

    monkeypatch.setattr(provider_mod, "get_astock_stock_data", fake_stock_data)
    monkeypatch.setitem(route_to_vendor.__globals__["VENDOR_METHODS"]["get_stock_data"], "a_stock_data", fake_stock_data)

    out = route_to_vendor("get_stock_data", "sh600519", "2026-01-01", "2026-01-10")

    assert "# A-Share Stock Data" in out
    assert "2026-01-02" in out


@pytest.mark.unit
def test_serialize_envelope_includes_contract_metadata():
    env = ProviderEnvelope(
        status="ok",
        source="fallback_source",
        as_of="2026-01-02",
        data={"records": [{"date": "2026-01-02", "value": 1}]},
        contract_fulfilled=False,
        fallback_level="partial",
    )

    out = provider_mod.serialize_envelope(env, title="A-Share Demo")

    assert "# Contract Fulfilled: false" in out
    assert "# Fallback Level: partial" in out


@pytest.mark.unit
def test_sina_financial_report_uses_report_type(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=15):
        calls.append(params)
        return _FakeResponse(
            {
                "result": {
                    "data": {
                        "report_list": {
                            "20260331": {
                                "data": [
                                    {"item_title": "净利润", "item_value": "100", "item_tongbi": "5%"}
                                ]
                            }
                        }
                    }
                }
            }
        )

    monkeypatch.setattr(provider_mod.requests, "get", fake_get)

    rows = AStockDataProvider().sina_financial_report("600519", "llb", num=1)

    assert calls[0]["source"] == "llb"
    assert rows[0]["报告期"] == "2026-03-31"
    assert rows[0]["净利润"] == "100"
    assert rows[0]["净利润_同比"] == "5%"


@pytest.mark.unit
def test_cninfo_orgid_dynamic_map_and_fallback(monkeypatch):
    provider_mod._CNINFO_ORGID_MAP = {}

    monkeypatch.setattr(
        provider_mod.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse({"stockList": [{"code": "601318", "orgId": "9900002221"}]}),
    )

    p = AStockDataProvider()
    assert p._cninfo_orgid("601318") == "9900002221"
    assert p._cninfo_orgid("600519") == "gssh0600519"


@pytest.mark.unit
def test_eastmoney_stock_news_uses_em_get(monkeypatch):
    calls = []
    payload = {
        "result": {
            "cmsArticleWebOld": [
                {
                    "title": "<em>标题</em>",
                    "content": "<p>内容</p>",
                    "date": "2026-01-01",
                    "mediaName": "东财",
                    "url": "https://example.com",
                }
            ]
        }
    }

    def fake_em_get(url, params=None, headers=None, timeout=15, **kwargs):
        calls.append(url)
        return _FakeResponse(text="jQuery_news(" + json.dumps(payload, ensure_ascii=False) + ")")

    monkeypatch.setattr(provider_mod, "em_get", fake_em_get)

    rows = AStockDataProvider().eastmoney_stock_news("600519")

    assert calls == ["https://search-api-web.eastmoney.com/search/jsonp"]
    assert rows[0]["title"] == "标题"
    assert rows[0]["content"] == "内容"


@pytest.mark.unit
def test_failure_paths_return_error_envelope(monkeypatch):
    monkeypatch.setattr(provider_mod.urllib.request, "urlopen", MagicMock(side_effect=RuntimeError("network down")))

    env = AStockDataProvider().get_quote("600519.SH")

    assert env.status == "error"
    assert env.errors


@pytest.mark.unit
def test_iwencai_without_key_returns_unavailable(monkeypatch):
    monkeypatch.delenv("IWENCAI_API_KEY", raising=False)
    monkeypatch.delenv("WENCAI_API_KEY", raising=False)

    env = AStockDataProvider().get_iwencai_reports("白酒行业研报", limit=5)

    assert env.status == "unavailable"
    assert env.source == "iwencai"


@pytest.mark.unit
def test_iwencai_tries_comprehensive_endpoint_and_extracts_records(monkeypatch):
    calls = []
    monkeypatch.setenv("IWENCAI_API_KEY", "test-key")
    monkeypatch.delenv("IWENCAI_ENDPOINT", raising=False)

    def fake_post(url, json=None, headers=None, timeout=20):
        calls.append((url, json, headers))
        return _FakeResponse({"data": {"report": {"records": [{"title": "研报"}]}}})

    monkeypatch.setattr(provider_mod.requests, "post", fake_post)

    env = AStockDataProvider().get_iwencai_reports("白酒行业研报", limit=5)

    assert env.status == "ok"
    assert calls[0][0].endswith("/v1/comprehensive/search")
    assert calls[0][1]["channels"] == ["report"]
    assert calls[0][2]["Authorization"] == "Bearer test-key"
    assert env.data["records"][0]["title"] == "研报"


@pytest.mark.unit
def test_iwencai_401_returns_diagnostic_error(monkeypatch):
    class UnauthorizedResponse(_FakeResponse):
        status_code = 401

        def __init__(self):
            super().__init__({"message": "unauthorized"})
            self.status_code = 401

    monkeypatch.setenv("IWENCAI_API_KEY", "bad-key")
    monkeypatch.setenv("IWENCAI_ENDPOINT", "/api/report-search")
    monkeypatch.setattr(provider_mod.requests, "post", lambda *args, **kwargs: UnauthorizedResponse())

    env = AStockDataProvider().get_iwencai_reports("白酒行业研报", limit=5)

    assert env.status == "error"
    assert "authentication failed" in env.errors[0]


@pytest.mark.unit
def test_baidu_empty_list_result_is_parsed_as_empty_payload(monkeypatch):
    monkeypatch.setattr(
        provider_mod.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse({"Result": []}),
    )

    payload = AStockDataProvider().baidu_kline_with_ma("000547")

    assert payload == {"keys": [], "rows": []}


@pytest.mark.unit
def test_stock_data_falls_back_to_eastmoney_kline(monkeypatch):
    provider = AStockDataProvider()
    records = [
        {"Date": "2026-06-03", "Open": 10, "High": 11, "Low": 9, "Close": 10.5, "Volume": 1000},
        {"Date": "2026-06-04", "Open": 10.5, "High": 12, "Low": 10, "Close": 11.5, "Volume": 1200},
    ]
    monkeypatch.setattr(provider, "_mootdx_bars", MagicMock(side_effect=RuntimeError("mootdx down")))
    monkeypatch.setattr(provider, "_baidu_kline_records", lambda code: [])
    monkeypatch.setattr(provider, "_eastmoney_kline_records", lambda code, start, end: records)

    env = provider.get_stock_data("000547.SZ", "2026-06-01", "2026-06-05")

    assert env.status == "ok"
    assert env.source == "eastmoney_kline"
    assert "mootdx down" in "; ".join(env.errors)
    assert "2026-06-04" in env.data["csv"]


@pytest.mark.unit
def test_sina_kline_jsonp_parser(monkeypatch):
    body = '/*redirect*/\nvar data=([{"day":"2026-06-04","open":"10.0","high":"11.0","low":"9.5","close":"10.5","volume":"12300"}]);'
    monkeypatch.setattr(provider_mod.requests, "get", lambda *args, **kwargs: _FakeResponse(text=body))

    rows = AStockDataProvider()._sina_kline_records("000547", datalen=1)

    assert rows[0]["Date"] == "2026-06-04"
    assert rows[0]["Close"] == 10.5
    assert rows[0]["Volume"] == 12300


@pytest.mark.unit
def test_stock_data_falls_back_to_sina_kline(monkeypatch):
    provider = AStockDataProvider()
    records = [
        {"Date": "2026-06-04", "Open": 10, "High": 11, "Low": 9, "Close": 10.5, "Volume": 1000},
    ]
    monkeypatch.setattr(provider, "_mootdx_bars", MagicMock(side_effect=RuntimeError("mootdx down")))
    monkeypatch.setattr(provider, "_baidu_kline_records", lambda code: [])
    monkeypatch.setattr(provider, "_eastmoney_kline_records", MagicMock(side_effect=RuntimeError("eastmoney down")))
    monkeypatch.setattr(provider, "_sina_kline_records", lambda code: records)

    env = provider.get_stock_data("000547.SZ", "2026-06-01", "2026-06-05")

    assert env.status == "ok"
    assert env.source == "sina_kline"
    assert env.contract_fulfilled is True
    assert env.fallback_level == "equivalent"
    assert "eastmoney down" in "; ".join(env.errors)


@pytest.mark.unit
def test_mootdx_market_data_falls_back_to_eastmoney_and_tencent(monkeypatch):
    provider = AStockDataProvider()
    records = [
        {"Date": "2026-06-04", "Open": 10, "High": 11, "Low": 9, "Close": 10.5, "Volume": 1000},
    ]
    monkeypatch.setattr(provider, "_client", lambda: object())
    monkeypatch.setattr(provider, "_mootdx_bars", MagicMock(side_effect=RuntimeError("mootdx down")))
    monkeypatch.setattr(provider, "_eastmoney_kline_records", lambda code, start, end: records)
    monkeypatch.setattr(provider, "tencent_quote", lambda codes: {"000547": {"price": 10.5}})

    env = provider.get_mootdx_market_data("000547.SZ", "2026-06-05")

    assert env.status == "ok"
    assert env.source == "mootdx_market_data_fallback"
    assert env.data["quote"][0]["price"] == 10.5


@pytest.mark.unit
def test_mootdx_f10_falls_back_to_public_company_info(monkeypatch):
    class FailingClient:
        def F10(self, **kwargs):
            raise RuntimeError("mootdx down")

    provider = AStockDataProvider()
    monkeypatch.setattr(provider, "_client", lambda: FailingClient())
    monkeypatch.setattr(provider, "eastmoney_stock_info", lambda code: {"code": code, "name": "航天发展"})

    env = provider.get_f10("000547.SZ", category="公司概况")

    assert env.status == "ok"
    assert env.source == "mootdx_f10_fallback"
    assert "航天发展" in env.data["text"]


@pytest.mark.unit
def test_eastmoney_stock_info_falls_back_to_public_quote(monkeypatch):
    provider = AStockDataProvider()
    monkeypatch.setattr(provider, "eastmoney_stock_info", MagicMock(side_effect=RuntimeError("push2 down")))
    monkeypatch.setattr(provider, "tencent_quote", lambda codes: {"000547": {"name": "航天发展", "price": 12.3, "mcap_yi": 120}})
    monkeypatch.setattr(provider, "eastmoney_reports", lambda code, max_pages=1: [{"indvInduName": "军工"}])

    env = provider.get_eastmoney_stock_info("000547.SZ")

    assert env.status == "ok"
    assert env.source == "eastmoney_stock_info_fallback_public"
    assert env.contract_fulfilled is False
    assert env.fallback_level == "partial"
    assert env.data["info"]["name"] == "航天发展"
    assert env.data["info"]["industry"] == "军工"
    assert "push2 down" in env.errors[0]
