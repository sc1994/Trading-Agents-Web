"""Offline Chinese equity-name snapshot for search; never fetch in a request."""

import argparse
import json
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def main(argv=None, fetch=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the Chinese equity search snapshot")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(os.environ.get("TRADINGAGENTS_WEB_DATA_DIR", "data/web")) / "assets.json",
    )
    args = parser.parse_args(argv)
    print(f"Published {refresh_catalog(args.path, fetch=fetch)} instruments")
    return 0


def fetch_akshare():
    import akshare as ak

    for board in ("主板A股", "科创板"):
        for _, row in ak.stock_info_sh_name_code(symbol=board).iterrows():
            yield "SH", str(row["证券代码"]), str(row["证券简称"])
    for _, row in ak.stock_info_sz_name_code(symbol="A股列表").iterrows():
        yield "SZ", str(row["A股代码"]), str(row["A股简称"])
    try:
        hong_kong = ak.stock_hk_spot_em()
        if len(hong_kong) < 1000:
            raise ValueError("incomplete Eastmoney HK list")
        for _, row in hong_kong.iterrows():
            yield "HK", str(row["代码"]), str(row["名称"])
    except Exception:
        logger.warning("Eastmoney HK list unavailable; trying Sina")
        for _, row in ak.stock_hk_spot().iterrows():
            yield "HK", str(row["代码"]), str(row["中文名称"])


def refresh_catalog(path: Path, fetch=None) -> int:
    """Publish a complete snapshot, leaving the prior one untouched on failure."""
    path = Path(path)
    production = fetch is None
    entries = {}
    counts = {"SH": 0, "SZ": 0, "HK": 0}
    for market, code, name in (fetch or fetch_akshare)():
        code, name = str(code).strip(), str(name).strip()
        if not name:
            continue
        if market in {"SH", "SZ"} and re.fullmatch(r"\d{6}", code):
            symbol, exchange = f"{code}.{'SS' if market == 'SH' else 'SZ'}", market
        elif market == "HK" and re.fullmatch(r"0\d{4}", code):
            symbol, exchange = f"{code[1:]}.HK", "HKEX"
        else:
            continue
        if symbol not in entries:
            counts[market] += 1
        entries[symbol] = {"symbol": symbol, "name": name, "exchange": exchange, "type": "EQUITY"}
    minimum = 1000 if production else 1
    if any(count < minimum for count in counts.values()):
        raise ValueError("incomplete instrument catalog")

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_mode & 0o7777 != 0o700:
        raise ValueError("catalog directory must be private (0700)")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".assets-",
            suffix=".json",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump({"assets": list(entries.values())}, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(entries)


def search_catalog(path: Path, query: str) -> list[dict]:
    try:
        with Path(path).open(encoding="utf-8") as source:
            assets = json.load(source)["assets"]
        if not isinstance(assets, list):
            return []
        needle = query.strip().casefold()
        matches = [
            item
            for item in assets
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("symbol"), str)
            and (needle in item["name"].casefold() or needle in item["symbol"].casefold())
        ]
        matches.sort(
            key=lambda item: (
                item["name"].casefold() != needle,
                not item["name"].casefold().startswith(needle),
                item["symbol"],
            )
        )
        return matches[:8]
    except (OSError, ValueError, KeyError, TypeError):
        return []


if __name__ == "__main__":
    raise SystemExit(main())
