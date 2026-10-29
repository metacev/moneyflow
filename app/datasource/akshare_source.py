"""akshare 免费A股数据源。

优先级：本地CSV缓存（当日有效） -> akshare 在线拉取。
akshare 未安装或网络失败时抛出 DataSourceError，由 manager 回退到模拟数据。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pandas as pd

from app.config import CACHE_DIR
from .base import DataSource, DataSourceError

COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
}


class AkshareSource(DataSource):
    key = "akshare"
    label = "akshare 免费行情"
    simulated = False

    def __init__(self, bars: int = 600) -> None:
        self.bars = bars
        self._ak = None
        self._last_error = ""

    def available(self) -> tuple[bool, str]:
        try:
            import akshare  # noqa: F401
        except Exception as e:  # pragma: no cover - 取决于环境
            return False, f"未安装 akshare（{e.__class__.__name__}）"
        return True, "akshare 在线免费行情（首次拉取较慢，之后走本地缓存）"

    def _get_ak(self):
        if self._ak is None:
            import akshare as ak

            self._ak = ak
        return self._ak

    def _cache_path(self, symbol: str):
        return CACHE_DIR / f"ak_{symbol}.csv"

    def _read_cache(self, symbol: str) -> pd.DataFrame | None:
        p = self._cache_path(symbol)
        if not p.exists():
            return None
        if datetime.now() - datetime.fromtimestamp(p.stat().st_mtime) > timedelta(hours=12):
            return None
        try:
            return pd.read_csv(p, dtype={"date": str})
        except Exception:
            return None

    def daily_bars(self, symbol: str, days: int = 600) -> pd.DataFrame:
        cached = self._read_cache(symbol)
        if cached is not None and len(cached) >= min(days, 120):
            return cached.tail(days).reset_index(drop=True)

        try:
            ak = self._get_ak()
            start = (datetime.now() - timedelta(days=int(days * 1.8) + 60)).strftime("%Y%m%d")
            end = datetime.now().strftime("%Y%m%d")
            raw = ak.stock_zh_a_hist(
                symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq"
            )
            if raw is None or raw.empty:
                raise DataSourceError("akshare 返回空数据")
            df = raw.rename(columns=COLUMN_MAP)
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                if col not in df.columns:
                    raise DataSourceError(f"akshare 缺少列 {col}")
                df[col] = pd.to_numeric(df[col], errors="coerce")
            if "turnover" not in df.columns:
                df["turnover"] = (df["amount"] / df["close"]) / 2.0e9 * 100
            df["date"] = df["date"].astype(str).str.slice(0, 10)
            df = df[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]]
            df = df.dropna(subset=["close"]).reset_index(drop=True)
            df.to_csv(self._cache_path(symbol), index=False)
            return df.tail(days).reset_index(drop=True)
        except Exception as e:
            self._last_error = str(e)
            raise DataSourceError(f"akshare 拉取 {symbol} 失败：{e}") from e

    def snapshot(self, symbol: str) -> dict | None:
        try:
            ak = self._get_ak()
            raw = ak.stock_bid_ask_em(symbol=symbol)
            if raw is None or raw.empty:
                return None
            data = dict(zip(raw["item"], raw["value"]))
            price = float(data.get("最新", 0) or 0)
            if price <= 0:
                return None
            return {
                "price": price,
                "prev_close": float(data.get("昨收", price) or price),
                "high": float(data.get("最高", price) or price),
                "low": float(data.get("最低", price) or price),
                "volume": float(data.get("总手", 0) or 0) * 100,
                "time": datetime.now().isoformat(timespec="seconds"),
            }
        except Exception:
            return None


def is_trading_time(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (9 * 60 + 30 <= t <= 11 * 60 + 30) or (13 * 60 <= t <= 15 * 60)
