"""因子引擎：把K线DataFrame转换成因子序列 + 前端可直接渲染的快照JSON。"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from .library import BANDS, DIRECTIONAL_WEIGHTS, FACTORS, level_index


def compute_frame(df: pd.DataFrame) -> pd.DataFrame:
    """在K线上叠加全部因子的原始值与评分列（r_<id> / s_<id>），完全向量化。"""
    out = df.copy().reset_index(drop=True)
    for f in FACTORS:
        raw, score = f["compute"](out)
        out[f"r_{f['id']}"] = pd.Series(raw).reset_index(drop=True)
        out[f"s_{f['id']}"] = pd.Series(score).clip(-100, 100).fillna(0.0).reset_index(drop=True)
    # 图表用均线
    for n in (5, 10, 20, 60):
        out[f"ma{n}"] = out["close"].rolling(n, min_periods=n).mean()
    return out


def _round_list(series: pd.Series, nd: int = 2) -> list:
    return [None if pd.isna(v) else round(float(v), nd) for v in series]


def composite_score(frame: pd.DataFrame) -> pd.Series:
    total_w = sum(DIRECTIONAL_WEIGHTS.values())
    acc = pd.Series(0.0, index=frame.index)
    for fid, w in DIRECTIONAL_WEIGHTS.items():
        acc = acc + frame[f"s_{fid}"].fillna(0) * w
    return (acc / total_w).clip(-100, 100)


COMPOSITE_LABELS = [
    (-100, "强空", "多数因子转空，谨慎抄底，优先控制回撤"),
    (-45, "偏空", "空头因子占优，反弹高度有限，宜轻仓观望"),
    (-15, "中性偏空", "多空拉锯，等待方向确认"),
    (15, "中性", "方向不明，适合等待信号共振"),
    (45, "偏多", "多头因子占优，可关注回踩后的介入机会"),
    (101, "强多", "多数因子共振向上，趋势行情概率较大"),
]


def composite_label(score: float) -> tuple[str, str]:
    for th, label, desc in COMPOSITE_LABELS:
        if score < th:
            return label, desc
    return "强多", COMPOSITE_LABELS[-1][2]


def build_snapshot(
    frame: pd.DataFrame,
    symbol: str,
    name: str,
    meta: dict,
    bars: int = 250,
    spark: int = 60,
    history: int = 160,
) -> dict:
    """生成前端完整快照（初次加载用）。"""
    if frame.empty:
        raise ValueError("空行情数据")

    last = frame.iloc[-1]
    prev_close = float(frame["close"].iloc[-2]) if len(frame) > 1 else float(last["close"])
    price = float(last["close"])
    change = price - prev_close
    change_pct = change / prev_close * 100 if prev_close else 0.0

    factors: list[dict] = []
    for f in FACTORS:
        sc = frame[f"s_{f['id']}"]
        raw = frame[f"r_{f['id']}"]
        score = float(sc.iloc[-1])
        lvl = level_index(score)
        window = sc.tail(250)
        pct_rank = float((window < score).mean() * 100)
        delta5 = float(score - (sc.iloc[-6] if len(sc) > 6 else sc.iloc[0]))
        # 连续处于同一档的天数
        dur = 0
        for v in sc.iloc[::-1]:
            if level_index(float(v)) == lvl:
                dur += 1
            else:
                break
        raw_val = float(raw.iloc[-1]) if pd.notna(raw.iloc[-1]) else 0.0
        item = {
            "id": f["id"],
            "name": f["name"],
            "short": f["short"],
            "category": f["category"],
            "unit": f["unit"],
            "weight": f["weight"],
            "weight_note": f["weight_note"],
            "meaning": f["meaning"],
            "role": f["role"],
            "formula": f["formula"],
            "levels": f["levels"],
            "value": round(raw_val, 4),
            "display": f["fmt"].format(raw_val),
            "score": round(score, 1),
            "level": lvl,
            "state": f["levels"][lvl],
            "pct_rank": round(pct_rank, 0),
            "delta5": round(delta5, 1),
            "duration": int(dur),
            "spark": _round_list(sc.tail(spark), 1),
        }
        factors.append(item)

    comp_series = composite_score(frame)
    comp = float(comp_series.iloc[-1])
    comp_label, comp_desc = composite_label(comp)
    directional = [x for x in factors if x["weight"] > 0]
    bull = sum(1 for x in directional if x["score"] >= 20)
    bear = sum(1 for x in directional if x["score"] <= -20)
    neutral = len(directional) - bull - bear

    kline_frame = frame.tail(bars)
    history_frame = frame.tail(history)

    return {
        "type": "snapshot",
        "symbol": symbol,
        "name": name,
        "time": datetime.now().isoformat(timespec="seconds"),
        "source": meta,
        "quote": {
            "price": round(price, 2),
            "prev_close": round(prev_close, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "open": round(float(last["open"]), 2),
            "high": round(float(last["high"]), 2),
            "low": round(float(last["low"]), 2),
            "volume": float(last["volume"]),
            "turnover": round(float(last.get("turnover", 0) or 0), 2),
            "date": str(last["date"]),
        },
        "kline": {
            "dates": [str(d) for d in kline_frame["date"]],
            "ohlc": [
                [round(float(o), 2), round(float(c), 2), round(float(l), 2), round(float(h), 2)]
                for o, c, l, h in zip(
                    kline_frame["open"], kline_frame["close"], kline_frame["low"], kline_frame["high"]
                )
            ],
            "volume": [round(float(v), 0) for v in kline_frame["volume"]],
            "ma5": _round_list(kline_frame["ma5"]),
            "ma10": _round_list(kline_frame["ma10"]),
            "ma20": _round_list(kline_frame["ma20"]),
            "ma60": _round_list(kline_frame["ma60"]),
        },
        "factors": factors,
        "composite": {
            "score": round(comp, 1),
            "label": comp_label,
            "desc": comp_desc,
            "bull": bull,
            "bear": bear,
            "neutral": neutral,
            "total_weight": sum(DIRECTIONAL_WEIGHTS.values()),
            "history": _round_list(comp_series.tail(history), 1),
        },
        "factor_history": {
            "dates": [str(d) for d in history_frame["date"]],
            "series": {f["id"]: _round_list(history_frame[f"s_{f['id']}"], 1) for f in FACTORS},
        },
        "bands": BANDS,
    }


def build_tick(frame: pd.DataFrame, snapshot_meta: dict) -> dict:
    """实时增量：只发报价、因子当前值和迷你走势，前端合并到已有快照。"""
    last = frame.iloc[-1]
    prev_close = float(snapshot_meta.get("prev_close", last["close"]))
    price = float(last["close"])
    factors = []
    for f in FACTORS:
        sc = frame[f"s_{f['id']}"]
        raw = frame[f"r_{f['id']}"]
        score = float(sc.iloc[-1])
        lvl = level_index(score)
        raw_val = float(raw.iloc[-1]) if pd.notna(raw.iloc[-1]) else 0.0
        factors.append(
            {
                "id": f["id"],
                "value": round(raw_val, 4),
                "display": f["fmt"].format(raw_val),
                "score": round(score, 1),
                "level": lvl,
                "state": f["levels"][lvl],
                "spark": _round_list(sc.tail(60), 1),
                "delta5": round(float(score - (sc.iloc[-6] if len(sc) > 6 else sc.iloc[0])), 1),
            }
        )
    comp = composite_score(frame)
    c = float(comp.iloc[-1])
    label, desc = composite_label(c)
    directional = [x for x in factors if FACTOR_WEIGHT(x["id"]) > 0]
    return {
        "type": "tick",
        "time": datetime.now().isoformat(timespec="seconds"),
        "quote": {
            "price": round(price, 2),
            "prev_close": round(prev_close, 2),
            "change": round(price - prev_close, 2),
            "change_pct": round((price / prev_close - 1) * 100, 2) if prev_close else 0.0,
            "open": round(float(last["open"]), 2),
            "high": round(float(last["high"]), 2),
            "low": round(float(last["low"]), 2),
            "volume": float(last["volume"]),
            "turnover": round(float(last.get("turnover", 0) or 0), 2),
            "date": str(last["date"]),
        },
        "bar": [round(float(last["open"]), 2), round(float(last["close"]), 2), round(float(last["low"]), 2), round(float(last["high"]), 2)],
        "bar_volume": round(float(last["volume"]), 0),
        "factors": factors,
        "composite": {
            "score": round(c, 1),
            "label": label,
            "desc": desc,
            "bull": sum(1 for x in directional if x["score"] >= 20),
            "bear": sum(1 for x in directional if x["score"] <= -20),
            "neutral": sum(1 for x in directional if -20 < x["score"] < 20),
            "history_tail": round(float(comp.iloc[-1]), 1),
        },
    }


_WEIGHTS = {f["id"]: f["weight"] for f in FACTORS}


def FACTOR_WEIGHT(fid: str) -> int:  # noqa: N802
    return _WEIGHTS.get(fid, 0)
