r"""佣金宝 QMT（迅投 xtquant）数据源适配器。

本文件已按 QMT 官方 xtquant 接口写好，装上 miniQMT 并登录后即可直接使用：
  pip install xtquant   （或在 QMT 安装目录 \bin.x64\Lib\site-packages 中找到）
  配置 config.json -> qmt.mini_qmt_path 指向 miniQMT 的 userdata_mini 目录

交易下单能力（xttrader）本版本未启用，后续接入点见文件末尾注释。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pandas as pd

from .base import DataSource, DataSourceError


def to_qmt_code(symbol: str) -> str:
    """600519 -> 600519.SH；000001 -> 000001.SZ；430047 -> 430047.BJ"""
    s = symbol.strip()
    if "." in s:
        return s.upper()
    if s.startswith(("6", "5", "9")):
        return f"{s}.SH"
    if s.startswith(("4", "8")):
        return f"{s}.BJ"
    return f"{s}.SZ"


class QmtSource(DataSource):
    key = "qmt"
    label = "佣金宝 QMT 行情"
    simulated = False

    def __init__(self, bars: int = 600) -> None:
        self.bars = bars
        self._xtdata = None

    def _get_xt(self):
        if self._xtdata is None:
            from xtquant import xtdata  # type: ignore

            self._xtdata = xtdata
        return self._xtdata

    def available(self) -> tuple[bool, str]:
        try:
            import xtquant  # noqa: F401
        except Exception:
            return False, "未检测到 xtquant（请安装 miniQMT 客户端并 pip install xtquant）"
        try:
            self._get_xt()
            return True, "QMT 行情已接入（需 miniQMT 已登录）"
        except Exception as e:  # pragma: no cover
            return False, f"xtquant 初始化失败：{e}"

    def daily_bars(self, symbol: str, days: int = 600) -> pd.DataFrame:
        try:
            xt = self._get_xt()
        except Exception as e:
            raise DataSourceError(f"xtquant 不可用：{e}") from e

        code = to_qmt_code(symbol)
        start = (datetime.now() - timedelta(days=int(days * 1.8) + 60)).strftime("%Y%m%d")
        try:
            xt.download_history_data(code, period="1d", start_time=start)
            data = xt.get_market_data_ex(
                ["open", "high", "low", "close", "volume", "amount"],
                [code],
                period="1d",
                start_time=start,
                end_time=datetime.now().strftime("%Y%m%d"),
                count=-1,
                dividend_type="front",
            )
            df = data.get(code)
        except Exception as e:
            raise DataSourceError(f"QMT 拉取 {code} 失败：{e}") from e

        if df is None or len(df) == 0:
            raise DataSourceError(f"QMT 返回空数据：{code}")

        df = df.reset_index()
        col = "index" if "index" in df.columns else df.columns[0]
        idx = df[col].astype(str).str.slice(0, 8)
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(idx, format="%Y%m%d").strftime("%Y-%m-%d"),
                "open": df["open"].astype(float),
                "high": df["high"].astype(float),
                "low": df["low"].astype(float),
                "close": df["close"].astype(float),
                "volume": df["volume"].astype(float),
                "amount": df.get("amount", df["close"] * df["volume"]).astype(float),
            }
        )
        out["turnover"] = (out["amount"] / out["close"]) / 2.0e9 * 100
        out = out[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]]
        out = out.dropna(subset=["close"]).tail(days).reset_index(drop=True)
        # QMT 当日可能包含未收盘K线
        return out

    def snapshot(self, symbol: str) -> dict | None:
        try:
            xt = self._get_xt()
            code = to_qmt_code(symbol)
            ticks = xt.get_full_tick([code])
            t = (ticks or {}).get(code)
            if not t:
                return None
            price = float(t.get("lastPrice") or 0)
            if price <= 0:
                return None
            return {
                "price": price,
                "prev_close": float(t.get("lastClose") or price),
                "high": float(t.get("high") or price),
                "low": float(t.get("low") or price),
                "volume": float(t.get("volume") or 0),
                "time": datetime.fromtimestamp(time.time()).isoformat(timespec="seconds"),
            }
        except Exception:
            return None

    def subscribe_realtime(self, symbol: str, callback) -> None:
        """订阅逐笔/分钟行情（后续实时推送可切换到这里）。"""
        xt = self._get_xt()
        code = to_qmt_code(symbol)
        xt.subscribe_quote(code, period="tick", callback=callback)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 后续接入交易能力的位置（本版本仅行情，不自动下单）：
#   from xtquant.xttrader import XtQuantTrader
#   from xtquant.xttype import StockAccount
#   trader = XtQuantTrader(mini_qmt_path, session_id); trader.start()
#   trader.connect(); acc = StockAccount(account_id); trader.order_stock(...)
# 建议先在模拟盘账号验证，再接入实盘。
# --------------------------------------------------------------------------
