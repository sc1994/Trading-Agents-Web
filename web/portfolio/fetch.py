"""Killable trusted upstream boundary; emit normalized JSON only."""

import contextlib
import json
import os
import re
import sys


def fetch(operation: str, payload: dict, ak) -> dict:
    if operation == "catalog":
        items = []
        sources = [
            ("SH", ak.stock_info_sh_name_code(symbol="主板A股"), "证券代码", "证券简称"),
            ("SH", ak.stock_info_sh_name_code(symbol="科创板"), "证券代码", "证券简称"),
            ("SZ", ak.stock_info_sz_name_code(symbol="A股列表"), "A股代码", "A股简称"),
            ("BJ", ak.stock_info_bj_name_code(), "证券代码", "证券简称"),
        ]
        for exchange, frame, code_key, name_key in sources:
            for _, row in frame.iterrows():
                code, name = str(row[code_key]).strip(), str(row[name_key]).strip()
                if not re.fullmatch(r"\d{6}", code) or not name:
                    raise ValueError("invalid catalog")
                items.append(
                    {
                        "symbol": f"{code}.{'SS' if exchange == 'SH' else exchange}",
                        "name": name,
                        "exchange": exchange,
                        "currency": "CNY",
                        "security_type": "A_SHARE",
                    }
                )
        return {"instruments": items, "source": "akshare_exchange_catalog"}
    if operation == "calendar":
        dates = ak.tool_trade_date_hist_sina()["trade_date"]
        return {"dates": sorted({str(value)[:10] for value in dates}), "source": "akshare_sina"}
    if operation == "quote":
        symbol, target = payload["symbol"], payload["target_date"]
        if not re.fullmatch(r"\d{6}\.(?:SS|SZ|BJ)", symbol) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", target
        ):
            raise ValueError("invalid quote request")
        frame = ak.stock_zh_a_hist(
            symbol=symbol[:6],
            period="daily",
            start_date=target.replace("-", ""),
            end_date=target.replace("-", ""),
            adjust="",
            timeout=10,
        )
        base = {"symbol": symbol, "currency": "CNY", "source": "akshare_eastmoney_unadjusted"}
        if frame.empty:
            return {**base, "error_code": "missing_quote"}
        row = frame.iloc[-1]
        return {
            **base,
            "price_date": str(row["日期"])[:10],
            "close": str(row["收盘"]),
            "volume": str(row["成交量"]),
            "error_code": None,
        }
    raise ValueError("unknown operation")


def main():
    try:
        import akshare as ak
    except ImportError:
        print(json.dumps({"error_code": "market_dependency_missing"}))
        return
    try:
        payload = json.loads(sys.stdin.read(8192))
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            result = fetch(sys.argv[1], payload, ak)
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
            raise ValueError("oversized upstream response")
    except Exception:
        encoded = json.dumps({"error_code": "market_unavailable"})
    print(encoded)


if __name__ == "__main__":
    main()
