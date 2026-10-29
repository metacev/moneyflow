"""内置模拟行情源：无需网络/密钥即可完整运行，用于开发、演示与离线回测。

使用确定性随机（按代码播种），保证每次生成的数据一致、回测结果可复现。
"""
from __future__ import annotations

import zlib
from datetime import datetime

import numpy as np
import pandas as pd

from .base import DataSource, BAR_COLUMNS


class MockSource(DataSource):
    key = "mock"
    label = "内置模拟行情"
    simulated = True

    def __init__(self, bars: int = 600) -> None:
        self.bars = bars
        self._cache: dict[str, pd.DataFrame] = {}

    def available(self) -> tuple[bool, str]:
        return True, "离线模拟数据（确定性随机行情），无需联网"

    def _base_price(self, symbol: str) -> float:
        # 常见标的用接近真实的价格区间，演示时更可信
        real = {
            "600519": 1480.0, "000001": 11.2, "300750": 252.0, "601318": 54.0,
            "000858": 128.0, "600036": 35.5, "601899": 18.6, "002594": 288.0,
            "600030": 25.4, "000333": 72.0, "601012": 17.8, "002415": 30.2,
        }
        if symbol in real:
            return real[symbol]
        h = zlib.crc32(symbol.encode())
        return float(8 + (h % 90) * 2.7)

    def _build(self, symbol: str, days: int) -> pd.DataFrame:
        seed = zlib.crc32(symbol.encode()) & 0x7FFFFFFF
        rng = np.random.default_rng(seed)
        n = days
        dates = pd.bdate_range(end=datetime.now().date(), periods=n)

        # 状态切换：每 20~60 天变换一次漂移/波动，模拟牛熊/震荡
        drift = np.zeros(n)
        vol = np.zeros(n)
        i = 0
        while i < n:
            seg = int(rng.integers(20, 61))
            j = min(n, i + seg)
            # 70% 上涨段 / 30% 下跌段，漂移按年化收益折算到日
            annual = rng.normal(0.18, 0.42)
            drift[i:j] = annual / 252
            vol[i:j] = rng.uniform(0.010, 0.030)
            i = j

        rets = drift + vol * rng.standard_normal(n)
        # 加入少量跳空与均值回归
        rets += rng.normal(0, 0.004, n)
        close = self._base_price(symbol) * np.exp(np.cumsum(rets))
        close = np.maximum(close, 1.0)

        prev_close = np.concatenate([[close[0] / (1 + rets[0])], close[:-1]])
        gap = rng.normal(0, 0.006, n)
        open_ = prev_close * (1 + gap)
        rng_amp = np.abs(rng.normal(0, 0.012, n)) + vol * rng.uniform(0.4, 1.2, n)
        high = np.maximum(open_, close) * (1 + rng_amp)
        low = np.minimum(open_, close) * (1 - rng_amp)

        # 成交量与波动率正相关
        base_vol = float(200 - (zlib.crc32(symbol.encode()) % 150)) * 1e5  # 股
        vol_noise = np.exp(rng.normal(0, 0.35, n))
        volume = base_vol * (0.6 + 2.2 * np.abs(rets) / np.maximum(vol, 1e-6)) * vol_noise
        volume = np.round(volume).astype(float)

        float_shares = 2.0e9 + (zlib.crc32(symbol.encode()) % 40) * 1e8
        turnover = volume / float_shares * 100

        df = pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "open": np.round(open_, 2),
                "high": np.round(high, 2),
                "low": np.round(low, 2),
                "close": np.round(close, 2),
                "volume": volume,
                "amount": np.round(volume * close, 2),
                "turnover": np.round(turnover, 3),
            }
        )
        return df[BAR_COLUMNS]

    def daily_bars(self, symbol: str, days: int = 600) -> pd.DataFrame:
        key = f"{symbol}:{days}"
        if key not in self._cache:
            self._cache[key] = self._build(symbol, days)
        return self._cache[key].copy()

    def snapshot(self, symbol: str) -> dict | None:
        return None
