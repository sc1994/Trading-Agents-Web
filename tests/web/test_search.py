import io
import json

from web.search import search_symbols


def test_chinese_catalog_results_do_not_wait_for_yahoo(tmp_path):
    from web.catalog import refresh_catalog

    path = tmp_path / "assets.json"
    refresh_catalog(path, fetch=lambda: [
        ("SH", "600000", "浦发银行"),
        ("SZ", "000001", "平安银行"),
        ("HK", "00780", "同程旅行"),
    ])

    calls = []

    def offline(query):
        calls.append(query)
        raise TimeoutError("Yahoo")

    assert search_symbols("同程", lookup=offline, catalog_path=path) == {
        "results": [{"symbol": "0780.HK", "name": "同程旅行", "exchange": "HKEX", "type": "EQUITY"}],
        "unavailable": False,
    }
    assert calls == []


def test_chinese_us_name_resolves_to_market_symbol_without_yahoo(tmp_path):
    payload = {"QuotationCodeTable": {"Data": [
        {
            "Code": "TCOM", "Name": "携程", "JYS": "NASDAQ",
            "Classify": "UsStock", "TypeUS": "3",
        },
        {
            "Code": "09961", "Name": "携程集团-S", "JYS": "HK",
            "Classify": "HK", "TypeUS": "3",
        },
        {
            "Code": "13241", "Name": "携程瑞银六乙购B", "JYS": "HK",
            "Classify": "HK", "TypeUS": "6",
        },
        {
            "Code": "600519", "Name": "贵州茅台", "JYS": "2",
            "Classify": "AStock", "TypeUS": "2", "MktNum": "1",
        },
        {
            "Code": "000001", "Name": "平安银行", "JYS": "6",
            "Classify": "AStock", "TypeUS": "6", "MktNum": "0",
        },
        {
            "Code": "300750", "Name": "宁德时代", "JYS": "80",
            "Classify": "AStock", "TypeUS": "80", "MktNum": "0",
        },
        {
            "Code": "AAPL", "Name": "苹果", "JYS": "NASDAQ",
            "Classify": "UsStock", "TypeUS": "1",
        },
        {
            "Code": "BRK_B", "Name": "伯克希尔哈撒韦-B", "JYS": "NYSE",
            "Classify": "UsStock", "TypeUS": "1",
        },
        {
            "Code": "QQQ", "Name": "纳斯达克100ETF-Invesco", "JYS": "NASDAQ",
            "Classify": "UsStock", "TypeUS": "5",
        },
        {
            "Code": "GRABW", "Name": "Grab Holdings Ltd Wt", "JYS": "NASDAQ",
            "Classify": "UsStock", "TypeUS": "8",
        },
        {
            "Code": "03032", "Name": "恒生科技ETF", "JYS": "HK",
            "Classify": "HK", "TypeUS": "1",
        },
        {
            "Code": "513180", "Name": "恒生科技ETF华夏", "JYS": "9",
            "Classify": "Fund", "TypeUS": "9", "MktNum": "1",
        },
        {
            "Code": "000847", "Name": "腾讯济安", "JYS": "1",
            "Classify": "Index", "TypeUS": "1", "MktNum": "1",
        },
    ]}}
    requests = []

    def open_search(url, timeout):
        requests.append((url, timeout))
        return io.BytesIO(json.dumps(payload).encode())

    assert search_symbols("携程", catalog_path=tmp_path / "missing.json", request=open_search) == {
        "results": [
            {"symbol": "TCOM", "name": "携程", "exchange": "NASDAQ", "type": "EQUITY"},
            {"symbol": "9961.HK", "name": "携程集团-S", "exchange": "HKEX", "type": "EQUITY"},
            {"symbol": "600519.SS", "name": "贵州茅台", "exchange": "SH", "type": "EQUITY"},
            {"symbol": "000001.SZ", "name": "平安银行", "exchange": "SZ", "type": "EQUITY"},
            {"symbol": "300750.SZ", "name": "宁德时代", "exchange": "SZ", "type": "EQUITY"},
            {"symbol": "AAPL", "name": "苹果", "exchange": "NASDAQ", "type": "EQUITY"},
            {"symbol": "BRK-B", "name": "伯克希尔哈撒韦-B", "exchange": "NYSE", "type": "EQUITY"},
        ],
        "unavailable": False,
    }
    assert len(requests) == 1
    assert "input=%E6%90%BA%E7%A8%8B" in requests[0][0]
    assert requests[0][1] == 5


def test_production_search_bounds_yahoo_request(monkeypatch):
    requests = []

    class FakeSearch:
        def __init__(self, query, **kwargs):
            requests.append((query, kwargs))
            self.quotes = []

    monkeypatch.setattr("web.search.yf.Search", FakeSearch)
    assert search_symbols("XYZQ") == {"results": [], "unavailable": False}
    assert requests == [("XYZQ", {
        "max_results": 8, "news_count": 0, "lists_count": 0, "recommended": 0, "timeout": 5,
    })]


def test_search_extracts_safe_fields():
    def lookup(query, **kwargs):
        assert query == "NVIDIA"
        return [{"symbol": "NVDA", "shortname": "NVIDIA", "exchDisp": "NASDAQ",
                 "quoteType": "EQUITY", "unsafe": "ignored"}]

    assert search_symbols("NVIDIA", lookup=lookup) == {"results": [
        {"symbol": "NVDA", "name": "NVIDIA", "exchange": "NASDAQ", "type": "EQUITY"}
    ], "unavailable": False}


def test_search_limits_result_count_and_prioritizes_exact_symbol():
    def lookup(query, **kwargs):
        return [{"symbol": f"NVDA{i}", "shortname": "Other"} for i in range(10)] + [
            {"symbol": "NVDA", "longname": "NVIDIA Corporation"}
        ]

    result = search_symbols("nvda", lookup=lookup)
    assert len(result["results"]) == 8
    assert result["results"][0] == {
        "symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "", "type": "",
    }


def test_empty_and_unavailable_searches_are_distinct():
    def empty(query, **kwargs):
        return []

    def timed_out(query, **kwargs):
        raise TimeoutError("Yahoo timeout")

    assert search_symbols("AMZN", lookup=empty) == {"results": [], "unavailable": False}
    assert search_symbols("AMZN", lookup=timed_out) == {"results": [], "unavailable": True}


def test_search_caches_same_query_for_ten_minutes(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    calls = []

    def lookup(query, **kwargs):
        calls.append(query)
        return [{"symbol": "AAPL", "shortname": "Apple"}]

    assert search_symbols(" AAPL ", lookup=lookup)["results"][0]["symbol"] == "AAPL"
    assert search_symbols("aapl", lookup=lookup)["results"][0]["symbol"] == "AAPL"
    assert calls == ["AAPL"]
    clock[0] = 601.0
    search_symbols("aapl", lookup=lookup)
    assert calls == ["AAPL", "aapl"]


def test_search_rejects_query_outside_server_limits():
    for query in ("", "a", "x" * 65):
        try:
            search_symbols(query, lookup=lambda *_args, **_kwargs: [])
        except ValueError as exc:
            assert "query" in str(exc)
        else:
            raise AssertionError("out-of-range query was accepted")
