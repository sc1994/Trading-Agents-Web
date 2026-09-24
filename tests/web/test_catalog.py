import json
import sys
from types import SimpleNamespace

import pytest

from web.catalog import fetch_akshare, main, refresh_catalog, search_catalog


def rows():
    return [
        ("SH", "600000", "浦发银行"),
        ("SZ", "000001", "平安银行"),
        ("HK", "00780", "同程旅行"),
        ("HK", "89988", "阿里巴巴-WR"),
    ]


def test_refresh_publishes_only_supported_markets_and_searches_chinese(tmp_path):
    path = tmp_path / "assets.json"
    refresh_catalog(path, fetch=rows)
    assert search_catalog(path, "同程") == [
        {"symbol": "0780.HK", "name": "同程旅行", "exchange": "HKEX", "type": "EQUITY"}
    ]
    assert search_catalog(path, "银行")[0]["symbol"] == "000001.SZ"
    assert search_catalog(path, "阿里") == []
    assert len(json.loads(path.read_text())["assets"]) == 3


def test_failed_or_empty_refresh_keeps_last_valid_snapshot(tmp_path):
    path = tmp_path / "assets.json"
    refresh_catalog(path, fetch=rows)
    old = path.read_bytes()

    def broken():
        raise TimeoutError("upstream")

    with pytest.raises(TimeoutError):
        refresh_catalog(path, fetch=broken)
    with pytest.raises(ValueError):
        refresh_catalog(path, fetch=lambda: [("HK", "00780", "同程旅行")])
    assert path.read_bytes() == old


def test_invalid_snapshot_does_not_crash_search(tmp_path):
    path = tmp_path / "assets.json"
    path.write_text("invalid")
    assert search_catalog(path, "同程") == []


def test_refresh_command_publishes_snapshot(tmp_path):
    path = tmp_path / "private" / "assets.json"
    assert main(["--path", str(path)], fetch=rows) == 0
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert search_catalog(path, "同程")[0]["symbol"] == "0780.HK"


def test_fetch_uses_sina_hk_list_when_eastmoney_disconnects(monkeypatch):
    class Frame:
        def __init__(self, records):
            self.records = records

        def iterrows(self):
            return enumerate(self.records)

    def eastmoney():
        raise ConnectionError("disconnected")

    fake = SimpleNamespace(
        stock_info_sh_name_code=lambda symbol: Frame(
            [{"证券代码": "600000", "证券简称": "浦发银行"}]
        ),
        stock_info_sz_name_code=lambda symbol: Frame(
            [{"A股代码": "000001", "A股简称": "平安银行"}]
        ),
        stock_hk_spot_em=eastmoney,
        stock_hk_spot=lambda: Frame([{"代码": "00780", "中文名称": "同程旅行"}]),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake)
    assert ("HK", "00780", "同程旅行") in list(fetch_akshare())
