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
