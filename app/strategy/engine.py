"""向量化友好的逐日回测引擎（A股规则：信号次日开盘成交、T+1、双边费用）。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _max_drawdown(equity: np.ndarray) -> tuple[float, int]:
    peak = np.maximum.accumulate(equity)
    dd = equity / np.where(peak == 0, np.nan, peak) - 1
    dd = np.nan_to_num(dd)
    idx = int(np.argmin(dd))
    return float(dd[idx]), idx


def run_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    initial_cash: float = 100000.0,
    fee_rate: float = 0.0003,
    slippage: float = 0.0002,
    allow_short: bool = False,
) -> dict:
    n = len(df)
    if n < 30:
        raise ValueError("行情数据太少，无法回测")
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    dates = df["date"].astype(str).tolist()
    sig = signals.to_numpy(dtype=int)

    cash = float(initial_cash)
    qty = 0.0
    equity = np.zeros(n, dtype=float)
    equity[0] = cash
    trades: list[dict] = []
    entry: dict | None = None

    def commission(amount: float) -> float:
        # 佣金（最低5元）+ 滑点已体现在成交价
        return max(amount * fee_rate, 5.0) if amount > 0 else 0.0

    for i in range(1, n):
        target = int(sig[i - 1])  # 昨收产生的信号，今日开盘执行
        if not allow_short:
            target = max(target, 0)
        px = opens[i]
        if px <= 0 or math.isnan(px):
            equity[i] = cash + qty * closes[i]
            continue

        side = 0
        want = 1 if target > 0 else (-1 if target < 0 else 0)
        cur = 1 if qty > 0 else (-1 if qty < 0 else 0)

        if want != cur:
            # 先平旧仓
            if cur != 0:
                deal_px = px * (1 - slippage) if cur > 0 else px * (1 + slippage)
                amount = abs(qty) * deal_px
                cash += qty * deal_px - commission(amount)
                if entry is not None:
                    pnl = (deal_px - entry["price"]) * entry["qty"]
                    trades.append(
                        {
                            "entry_date": entry["date"],
                            "exit_date": dates[i],
                            "direction": "多" if entry["qty"] > 0 else "空",
                            "entry_price": round(entry["price"], 2),
                            "exit_price": round(deal_px, 2),
                            "qty": round(abs(entry["qty"]), 0),
                            "pnl": round(float(pnl) - entry["fee"], 2),
                            "pnl_pct": round(float(pnl - entry["fee"]) / max(entry["cost"], 1) * 100, 2),
                            "hold_days": i - entry["idx"],
                        }
                    )
                    entry = None
                qty = 0.0
            # 再开新仓
            if want != 0:
                if want > 0:
                    target_qty = math.floor((cash * 0.995) / (px * (1 + slippage) * (1 + fee_rate)) / 100) * 100
                    deal_px = px * (1 + slippage)
                    if target_qty > 0 and target_qty * deal_px <= cash:
                        fee = commission(target_qty * deal_px)
                        cash -= target_qty * deal_px + fee
                        qty = float(target_qty)
                        entry = {"date": dates[i], "idx": i, "price": deal_px, "qty": qty, "fee": fee, "cost": target_qty * deal_px}
                else:
                    margin_qty = math.floor((cash * 0.5) / (px * (1 + slippage)) / 100) * 100
                    if margin_qty > 0:
                        deal_px = px * (1 - slippage)
                        fee = commission(margin_qty * deal_px)
                        cash += margin_qty * deal_px - fee
                        qty = -float(margin_qty)
                        entry = {"date": dates[i], "idx": i, "price": deal_px, "qty": qty, "fee": fee, "cost": margin_qty * deal_px}
        equity[i] = cash + qty * closes[i]

    # 收盘强平，结算最后一笔
    if qty != 0 and entry is not None:
        deal_px = closes[-1]
        amount = abs(qty) * deal_px
        fee = commission(amount)
        cash += qty * deal_px - fee
        pnl = (deal_px - entry["price"]) * entry["qty"] - entry["fee"] - fee
        trades.append(
            {
                "entry_date": entry["date"],
                "exit_date": dates[-1],
                "direction": "多" if entry["qty"] > 0 else "空",
                "entry_price": round(entry["price"], 2),
                "exit_price": round(deal_px, 2),
                "qty": round(abs(entry["qty"]), 0),
                "pnl": round(float(pnl), 2),
                "pnl_pct": round(float(pnl) / max(entry["cost"], 1) * 100, 2),
                "hold_days": n - 1 - entry["idx"],
            }
        )
        equity[-1] = cash
        qty = 0.0

    equity = np.maximum(equity, 0.01)
    total_return = equity[-1] / initial_cash - 1
    days = max(n - 1, 1)
    annual = (equity[-1] / initial_cash) ** (252 / days) - 1 if equity[-1] > 0 else -1.0
    rets = np.diff(equity) / equity[:-1]
    rets = rets[np.isfinite(rets)]
    sharpe = float(np.mean(rets) / np.std(rets) * math.sqrt(252)) if len(rets) > 2 and np.std(rets) > 0 else 0.0
    mdd, mdd_idx = _max_drawdown(equity)
    calmar = float(annual / abs(mdd)) if mdd < 0 else 0.0
    win = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(win) / len(trades) if trades else 0.0
    profit_factor = (
        sum(t["pnl"] for t in win) / abs(sum(t["pnl"] for t in losses))
        if losses and sum(t["pnl"] for t in losses) != 0
        else (float("inf") if win else 0.0)
    )
    exposure = float(np.mean(sig > 0))

    bench = closes / closes[0] * initial_cash
    bench_return = bench[-1] / initial_cash - 1

    # 图表标记：买卖点
    markers = []
    for t in trades:
        markers.append({"date": t["entry_date"], "price": t["entry_price"], "type": "buy" if t["direction"] == "多" else "sell"})
        markers.append({"date": t["exit_date"], "price": t["exit_price"], "type": "sell" if t["direction"] == "多" else "buy"})

    return {
        "dates": dates,
        "equity": [round(float(v), 2) for v in equity],
        "benchmark": [round(float(v), 2) for v in bench],
        "drawdown": [round(float(v * 100), 2) for v in (equity / np.maximum.accumulate(equity) - 1)],
        "metrics": {
            "total_return": round(float(total_return * 100), 2),
            "annual_return": round(float(max(min(annual, 9.99), -1.0) * 100), 2),
            "sharpe": round(sharpe, 2),
            "max_drawdown": round(float(mdd * 100), 2),
            "calmar": round(calmar, 2),
            "win_rate": round(float(win_rate * 100), 1),
            "trades": len(trades),
            "profit_factor": round(float(profit_factor), 2) if profit_factor != float("inf") else 999,
            "exposure": round(exposure * 100, 1),
            "benchmark_return": round(float(bench_return * 100), 2),
            "excess_return": round(float((total_return - bench_return) * 100), 2),
            "final_equity": round(float(equity[-1]), 2),
        },
        "trades": trades[-80:][::-1],
        "markers": markers,
        "signal": [int(v) for v in sig],
    }
