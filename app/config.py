"""应用配置：读写 data/config.json，支持环境变量覆盖 LLM 密钥。"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """静态资源目录；PyInstaller 打包后位于临时解包目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return ROOT


def _data_dir() -> Path:
    env = os.getenv("QFL_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return ROOT / "data"


DATA_DIR = _data_dir()
CACHE_DIR = DATA_DIR / "cache"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "data_source": "auto",  # auto | mock | akshare | qmt
    "symbols": ["600519", "000001", "300750", "601318", "000858"],
    "active_symbol": "600519",
    "tick_interval": 2.0,  # 秒，实时推送间隔
    "bars": 600,  # 加载的历史K线数量
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",
        "temperature": 0.3,
    },
    "backtest": {
        "initial_cash": 100000.0,
        "fee_rate": 0.0003,
        "slippage": 0.0002,
        "allow_short": False,
    },
    "qmt": {
        "mini_qmt_path": "",  # 如 C:\\国金QMT交易端\\userdata_mini
        "account_id": "",
    },
}

# 常用A股名称，避免每次都要联网查询
SYMBOL_NAMES = {
    "600519": "贵州茅台",
    "000001": "平安银行",
    "300750": "宁德时代",
    "601318": "中国平安",
    "000858": "五粮液",
    "600036": "招商银行",
    "601899": "紫金矿业",
    "002594": "比亚迪",
    "600030": "中信证券",
    "000333": "美的集团",
    "601012": "隆基绿能",
    "002415": "海康威视",
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(CONFIG_PATH.read_text("utf-8")))
        except Exception:
            pass
    env_key = os.getenv("LLM_API_KEY")
    if env_key:
        cfg["llm"]["api_key"] = env_key
    if os.getenv("LLM_BASE_URL"):
        cfg["llm"]["base_url"] = os.getenv("LLM_BASE_URL", "")
    if os.getenv("LLM_MODEL"):
        cfg["llm"]["model"] = os.getenv("LLM_MODEL", "")
    return cfg


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = _deep_merge(DEFAULTS, cfg)
    CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
    return merged


def public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """返回给前端时隐藏明文密钥（只标记是否已配置）。"""
    out = copy.deepcopy(cfg)
    key = out.get("llm", {}).get("api_key") or ""
    out["llm"]["api_key"] = ""
    out["llm"]["has_key"] = bool(key)
    out["llm"]["key_hint"] = (key[:4] + "***" + key[-4:]) if len(key) > 8 else ("已配置" if key else "")
    return out


def symbol_name(code: str) -> str:
    return SYMBOL_NAMES.get(code, code)
