"""实时行情中心：加载K线、模拟盘中tick、通过 WebSocket 推送因子状态。"""
from __future__ import annotations

import asyncio
import copy
import json
import math
import random
from datetime import datetime

import pandas as pd

from .config import symbol_name
from .datasource.akshare_source import is_trading_time
from .datasource.manager import DataSourceManager
from .factors.engine import build_snapshot, build_tick, compute_frame


class MarketHub:
    def __init__(self, cfg: dict, manager: DataSourceManager) -> None:
        self.cfg = cfg
        self.manager = manager
        self.clients: set = set()
        self.active_symbol: str = cfg.get("active_symbol") or cfg["symbols"][0]
        self.base_frames: dict[str, pd.DataFrame] = {}
        self.metas: dict[str, dict] = {}
        self.snap_meta: dict[str, dict] = {}
        self.sim: dict[str, dict] = {}
        self.frame_lock = asyncio.Lock()
        self.tick_interval = float(cfg.get("tick_interval", 2.0))
        self.tick_count = 0
        self._task: asyncio.Task | None = None
        self.last_update: str = ""

    # ------------------------------------------------------------------ 数据
    def _load(self, symbol: str, force: bool = False) -> None:
        if symbol in self.base_frames and not force:
            return
        days = int(self.cfg.get("bars", 600))
        df, meta = self.manager.bars(symbol, days)
        self.base_frames[symbol] = df.reset_index(drop=True)
        self.metas[symbol] = meta
        self._reset_sim(symbol)

    def _reset_sim(self, symbol: str) -> None:
        df = self.base_frames[symbol]
        last = df.iloc[-1]
        prev = float(df["close"].iloc[-2]) if len(df) > 1 else float(last["close"])
        atr_pct = 1.5
        try:
            tr = (
                df["high"].rolling(14).max() - df["low"].rolling(14).min()
            ) / df["close"]
            atr_pct = float(tr.iloc[-1] * 100) if pd.notna(tr.iloc[-1]) else 1.5
        except Exception:
            pass
        self.sim[symbol] = {
            "price": float(last["close"]),
            "prev_close": prev,
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "volume": float(last["volume"]),
            "sigma": min(0.004, max(0.0006, atr_pct / 100 * 0.12)),
            "day_volume_base": float(df["volume"].tail(20).mean()),
        }
        self.snap_meta[symbol] = {"prev_close": prev}

    def frame(self, symbol: str) -> pd.DataFrame:
        self._load(symbol)
        return compute_frame(self.base_frames[symbol])

    def snapshot(self, symbol: str) -> dict:
        self._load(symbol, force=False)
        frame = self.frame(symbol)
        return build_snapshot(frame, symbol, symbol_name(symbol), self.metas[symbol])

    def refresh(self, symbol: str) -> None:
        self._load(symbol, force=True)

    def _apply_real_quote(self, symbol: str) -> bool:
        """真实数据源且处于交易时段时，用实时快照覆盖当日K线。"""
        if self.manager.active is None or self.manager.active.simulated:
            return False
        if not is_trading_time():
            return False
        snap = self.manager.snapshot(symbol)
        if not snap:
            return False
        df = self.base_frames[symbol]
        i = df.index[-1]
        df.at[i, "close"] = snap["price"]
        df.at[i, "high"] = max(float(df.at[i, "high"]), snap["high"], snap["price"])
        df.at[i, "low"] = min(float(df.at[i, "low"]), snap["low"], snap["price"])
        df.at[i, "volume"] = max(float(df.at[i, "volume"]), snap["volume"])
        return True

    def _simulate_tick(self, symbol: str) -> None:
        st = self.sim[symbol]
        price = st["price"]
        prev = st["prev_close"]
        # 随机游走 + 向昨收的均值回归，避免长时间单调漂移
        drift = (prev / price - 1) * 0.02
        ret = random.gauss(0, st["sigma"]) + drift
        price = max(0.5, price * math.exp(ret))
        st["price"] = price
        st["high"] = max(st["high"], price)
        st["low"] = min(st["low"], price)
        st["volume"] += st["day_volume_base"] * random.uniform(0.001, 0.008)

        df = self.base_frames[symbol]
        i = df.index[-1]
        df.at[i, "close"] = round(price, 2)
        df.at[i, "high"] = round(st["high"], 2)
        df.at[i, "low"] = round(st["low"], 2)
        df.at[i, "volume"] = round(st["volume"], 0)
        df.at[i, "amount"] = round(st["volume"] * price, 0)
        if "turnover" in df.columns:
            df.at[i, "turnover"] = round(float(df.at[i, "turnover"]) + random.uniform(0.0, 0.01), 3)

    def step(self, symbol: str) -> dict:
        self._load(symbol)
        real = self._apply_real_quote(symbol)
        if not real:
            self._simulate_tick(symbol)
        frame = compute_frame(self.base_frames[symbol])
        tick = build_tick(frame, self.snap_meta.get(symbol, {}))
        tick["symbol"] = symbol
        tick["name"] = symbol_name(symbol)
        tick["simulated"] = not real
        tick["tick"] = self.tick_count
        self.last_update = tick["time"]
        return tick

    # --------------------------------------------------------------- 推送
    async def broadcast(self, message: dict) -> None:
        if not self.clients:
            return
        text = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def push_snapshot(self, symbol: str) -> None:
        data = await asyncio.to_thread(self.snapshot, symbol)
        await self.broadcast(data)

    async def subscribe(self, ws) -> None:
        self.clients.add(ws)
        data = await asyncio.to_thread(self.snapshot, self.active_symbol)
        await ws.send_text(json.dumps(data, ensure_ascii=False))

    async def switch(self, symbol: str, ws=None) -> None:
        async with self.frame_lock:
            self.active_symbol = symbol
            self._load(symbol)
        data = await asyncio.to_thread(self.snapshot, symbol)
        if ws is not None:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                pass
        else:
            await self.broadcast(data)

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.tick_interval)
                self.tick_count += 1
                tick = await asyncio.to_thread(self.step, self.active_symbol)
                await self.broadcast(tick)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1.0)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def status(self) -> dict:
        return {
            "active_symbol": self.active_symbol,
            "tick_interval": self.tick_interval,
            "clients": len(self.clients),
            "last_update": self.last_update,
            "source": self.manager.meta(),
        }
