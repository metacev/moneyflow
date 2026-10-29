"""数据源管理：按配置选择，失败自动回退，并记录实际使用的数据源状态。"""
from __future__ import annotations

import threading

import pandas as pd

from .akshare_source import AkshareSource
from .base import DataSource, DataSourceError
from .mock_source import MockSource
from .qmt_source import QmtSource


class DataSourceManager:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._lock = threading.Lock()
        self._sources: dict[str, DataSource] = {}
        self.active_key = ""
        self.active: DataSource | None = None
        self.notice = ""
        self.status: dict[str, dict] = {}
        self.reload()

    def _candidates(self) -> list[DataSource]:
        bars = int(self.cfg.get("bars", 600))
        return [QmtSource(bars), AkshareSource(bars), MockSource(bars)]

    def reload(self) -> None:
        with self._lock:
            wanted = (self.cfg.get("data_source") or "auto").lower()
            sources = {s.key: s for s in self._candidates()}
            self._sources = sources
            self.status = {}
            for k, s in sources.items():
                ok, msg = s.available()
                self.status[k] = {"available": ok, "message": msg, "label": s.label, "simulated": s.simulated}

            order = ["qmt", "akshare", "mock"] if wanted == "auto" else [wanted, "mock"]
            chosen: DataSource | None = None
            notice = ""
            for key in order:
                src = sources.get(key)
                if src is None:
                    continue
                if self.status.get(key, {}).get("available"):
                    chosen = src
                    break
                if key != "mock":
                    notice += f"{sources[key].label} 不可用，已跳过；"
            if chosen is None:
                chosen = sources["mock"]
                notice += "已回退到内置模拟行情。"

            self.active = chosen
            self.active_key = chosen.key
            self.notice = notice.strip()

    def _get(self, symbol: str, days: int) -> tuple[pd.DataFrame, dict]:
        assert self.active is not None
        src = self.active
        try:
            df = src.daily_bars(symbol, days)
            return df, self.meta()
        except DataSourceError as e:
            if src.key == "mock":
                raise
            # 运行中失败：降级到模拟数据，并在本次会话内记住该源不可用
            self.status.setdefault(src.key, {"label": src.label, "simulated": False})
            self.status[src.key]["available"] = False
            self.status[src.key]["message"] = str(e)
            mock = self._sources.get("mock")
            if mock is None:
                mock = MockSource()
            self.active = mock
            self.active_key = "mock"
            self.notice = f"{src.label} 不可用，已自动切换为内置模拟行情"
            df = mock.daily_bars(symbol, days)
            meta = self.meta()
            meta["fallback"] = True
            meta["fallback_reason"] = str(e)
            return df, meta

    def bars(self, symbol: str, days: int | None = None) -> tuple[pd.DataFrame, dict]:
        return self._get(symbol, int(days or self.cfg.get("bars", 600)))

    def snapshot(self, symbol: str) -> dict | None:
        if self.active is None:
            return None
        try:
            return self.active.snapshot(symbol)
        except Exception:
            return None

    def meta(self) -> dict:
        assert self.active is not None
        return {
            "source": self.active.key,
            "source_label": self.active.label,
            "simulated": self.active.simulated,
            "notice": self.notice,
            "fallback": False,
            "fallback_reason": "",
            "sources": self.status,
            "configured": self.cfg.get("data_source", "auto"),
        }
