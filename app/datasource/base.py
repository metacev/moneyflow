"""数据源抽象层：统一K线/快照接口，便于在 模拟数据 / akshare / 佣金宝QMT 之间切换。"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

# 标准K线列
BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]


class DataSourceError(RuntimeError):
    pass


class DataSource(ABC):
    key: str = "base"
    label: str = "数据源"
    simulated: bool = False

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """返回 (是否可用, 说明)。"""

    @abstractmethod
    def daily_bars(self, symbol: str, days: int = 600) -> pd.DataFrame:
        """返回按日期升序的标准K线 DataFrame（见 BAR_COLUMNS）。"""

    def snapshot(self, symbol: str) -> dict | None:
        """实时快照，返回 {'price','prev_close','high','low','volume','time'}，不支持则 None。"""
        return None

    def close(self) -> None:
        pass
