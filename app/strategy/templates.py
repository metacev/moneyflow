"""内置策略模板：参数化、可解释，同时支持用户自定义 generate_signals 代码。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.factors.library import DIRECTIONAL_WEIGHTS


class StrategyError(ValueError):
    pass


def _stateful(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """由开仓/平仓条件生成持仓序列（0/1），避免阈值反复抖动。"""
    pos = 0
    out = np.zeros(len(entry), dtype=int)
    e = entry.fillna(False).to_numpy()
    x = exit_.fillna(False).to_numpy()
    for i in range(len(e)):
        if pos == 0 and e[i]:
            pos = 1
        elif pos == 1 and x[i]:
            pos = 0
        out[i] = pos
    return pd.Series(out, index=entry.index)


def _composite(df: pd.DataFrame) -> pd.Series:
    total = sum(DIRECTIONAL_WEIGHTS.values())
    acc = pd.Series(0.0, index=df.index)
    for fid, w in DIRECTIONAL_WEIGHTS.items():
        col = f"s_{fid}"
        if col in df.columns:
            acc = acc + df[col].fillna(0.0) * w
    return (acc / total).fillna(0.0)


def _s_dual_ma(df: pd.DataFrame, p: dict) -> pd.Series:
    fast = df["close"].rolling(int(p["fast"]), min_periods=int(p["fast"])).mean()
    slow = df["close"].rolling(int(p["slow"]), min_periods=int(p["slow"])).mean()
    return (fast > slow).astype(int)


def _s_macd(df: pd.DataFrame, p: dict) -> pd.Series:
    ema = lambda n: df["close"].ewm(span=n, adjust=False).mean()  # noqa: E731
    dif = ema(int(p["fast"])) - ema(int(p["slow"]))
    dea = dif.ewm(span=int(p["signal"]), adjust=False).mean()
    return (dif > dea).astype(int)


def _s_rsi(df: pd.DataFrame, p: dict) -> pd.Series:
    rsi = df["r_rsi14"].fillna(50) if "r_rsi14" in df.columns else pd.Series(50, index=df.index)
    return _stateful(rsi < float(p["buy"]), rsi > float(p["sell"]))


def _s_boll(df: pd.DataFrame, p: dict) -> pd.Series:
    pctb = df["r_boll_pctb"].fillna(0.5) if "r_boll_pctb" in df.columns else pd.Series(0.5, index=df.index)
    return _stateful(pctb < float(p["buy"]), pctb > float(p["sell"]))


def _s_multi(df: pd.DataFrame, p: dict) -> pd.Series:
    comp = _composite(df)
    entry = comp > float(p["buy"])
    if p.get("trend_filter", True) and "s_ma_slope20" in df.columns:
        entry = entry & (df["s_ma_slope20"] > 0)
    exit_ = comp < float(p["sell"])
    return _stateful(entry, exit_)


def _s_custom(df: pd.DataFrame, p: dict) -> pd.Series:
    code = str(p.get("code") or "").strip()
    if not code:
        raise StrategyError("自定义策略代码为空")
    safe_builtins = {
        name: getattr(__builtins__, name, None)
        for name in [
            "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
            "int", "isinstance", "len", "list", "map", "max", "min", "range",
            "round", "set", "sorted", "str", "sum", "tuple", "zip", "ValueError",
            "Exception", "print",
        ]
    }
    safe_builtins = {k: v for k, v in safe_builtins.items() if v is not None}
    ns: dict = {"pd": pd, "np": np, "__builtins__": safe_builtins}
    try:
        exec(code, ns)  # noqa: S102 - 本地个人工具，允许自定义策略代码
    except Exception as e:
        raise StrategyError(f"代码执行失败：{e}") from e
    fn = ns.get("generate_signals")
    if not callable(fn):
        raise StrategyError("请定义函数 generate_signals(df, params)")
    try:
        out = fn(df, p)
    except Exception as e:
        raise StrategyError(f"generate_signals 运行出错：{e}") from e
    if isinstance(out, pd.DataFrame):
        out = out.iloc[:, 0]
    if not isinstance(out, pd.Series):
        out = pd.Series(out, index=df.index)
    return out


TEMPLATES: list[dict] = [
    {
        "id": "dual_ma",
        "name": "双均线趋势",
        "desc": "快线上穿慢线做多，下穿离场。最经典的趋势跟随，适合单边行情，震荡市回撤较多。",
        "params": [
            {"key": "fast", "label": "快线周期", "type": "int", "default": 5, "min": 2, "max": 60},
            {"key": "slow", "label": "慢线周期", "type": "int", "default": 20, "min": 10, "max": 250},
        ],
        "fn": _s_dual_ma,
    },
    {
        "id": "macd",
        "name": "MACD 金叉",
        "desc": "DIF 上穿 DEA 持有多头，下穿离场。对趋势转折更敏感，但震荡市假信号多。",
        "params": [
            {"key": "fast", "label": "快线EMA", "type": "int", "default": 12, "min": 3, "max": 60},
            {"key": "slow", "label": "慢线EMA", "type": "int", "default": 26, "min": 10, "max": 120},
            {"key": "signal", "label": "信号线", "type": "int", "default": 9, "min": 3, "max": 40},
        ],
        "fn": _s_macd,
    },
    {
        "id": "rsi_reversal",
        "name": "RSI 超跌反转",
        "desc": "RSI 跌破超卖线买入，回升到超买线卖出。逆势均值回归，适合震荡市。",
        "params": [
            {"key": "buy", "label": "买入阈值", "type": "int", "default": 30, "min": 5, "max": 45},
            {"key": "sell", "label": "卖出阈值", "type": "int", "default": 70, "min": 55, "max": 95},
        ],
        "fn": _s_rsi,
    },
    {
        "id": "boll_reversion",
        "name": "布林带回归",
        "desc": "价格触及下轨买入，触及上轨卖出。利用通道均值回归，单边下跌时需止损配合。",
        "params": [
            {"key": "buy", "label": "买入%B", "type": "float", "default": 0.05, "min": 0.0, "max": 0.4, "step": 0.01},
            {"key": "sell", "label": "卖出%B", "type": "float", "default": 0.95, "min": 0.6, "max": 1.0, "step": 0.01},
        ],
        "fn": _s_boll,
    },
    {
        "id": "multi_factor",
        "name": "多因子共振",
        "desc": "综合13个因子加权评分，评分高于阈值且趋势向上时做多，评分转弱离场。",
        "params": [
            {"key": "buy", "label": "买入评分", "type": "int", "default": 10, "min": 0, "max": 90},
            {"key": "sell", "label": "卖出评分", "type": "int", "default": -5, "min": -90, "max": 30},
            {"key": "trend_filter", "label": "趋势过滤", "type": "bool", "default": True},
        ],
        "fn": _s_multi,
    },
    {
        "id": "custom",
        "name": "自定义代码",
        "desc": "编写 Python 函数 generate_signals(df, params)，返回每日目标仓位 0/1（或 -1 做空）。",
        "params": [{"key": "code", "label": "策略代码", "type": "code", "default": ""}],
        "fn": _s_custom,
    },
]

TEMPLATE_MAP = {t["id"]: t for t in TEMPLATES}

DEFAULT_CODE = '''def generate_signals(df, params):
    """返回每日目标仓位序列：1=持有, 0=空仓（-1=做空）
    可用列: open/high/low/close/volume/turnover/ma5/ma20/ma60
    以及所有因子: r_<id> 原始值, s_<id> 评分(-100~100)
    例: 20日动量 > 0 且 乖离率未过热时持有
    """
    mom = df["s_mom20"]
    bias = df["s_ma_bias20"]
    hold = (mom > 10) & (bias < -40)
    return hold.astype(int)
'''


def generate_signals(strategy: str, df: pd.DataFrame, params: dict) -> pd.Series:
    tpl = TEMPLATE_MAP.get(strategy)
    if tpl is None:
        raise StrategyError(f"未知策略：{strategy}")
    merged = {}
    for spec in tpl["params"]:
        key = spec["key"]
        val = params.get(key, spec["default"])
        if spec["type"] == "code":
            merged[key] = val if val else DEFAULT_CODE
        elif spec["type"] == "int":
            merged[key] = int(val)
        elif spec["type"] == "float":
            merged[key] = float(val)
        elif spec["type"] == "bool":
            merged[key] = bool(val)
        else:
            merged[key] = val
    sig = tpl["fn"](df, merged)
    sig = pd.to_numeric(pd.Series(sig).reset_index(drop=True), errors="coerce").fillna(0)
    sig = sig.clip(-1, 1).round().astype(int)
    return sig
