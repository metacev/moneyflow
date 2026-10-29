"""大模型客户端：OpenAI 兼容协议（DeepSeek / 通义 / 智谱 / OpenAI 均可），流式输出。

未配置 API Key 时自动使用本地规则解读（app/llm/local.py），保证离线也能用。
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .local import local_factor_explain, local_strategy_hint


class LLMError(RuntimeError):
    pass


def configured(cfg: dict) -> bool:
    return bool((cfg.get("llm", {}) or {}).get("api_key"))


def _endpoint(base_url: str) -> str:
    base = (base_url or "https://api.deepseek.com/v1").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


async def stream_chat(cfg: dict, messages: list[dict]) -> AsyncIterator[str]:
    llm = cfg.get("llm", {})
    api_key = llm.get("api_key") or ""
    if not api_key:
        raise LLMError("未配置 API Key")
    payload = {
        "model": llm.get("model") or "deepseek-chat",
        "messages": messages,
        "stream": True,
        "temperature": float(llm.get("temperature", 0.3)),
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=20.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", _endpoint(llm.get("base_url", "")), json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "ignore")[:300]
                raise LLMError(f"大模型返回 {resp.status_code}：{body}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content")
                except Exception:
                    continue
                if delta:
                    yield delta


FACTOR_SYSTEM = (
    "你是一名严谨的A股量化研究员，擅长把因子讲清楚。要求：中文、结构清晰、只基于给定数据推断，"
    "不编造数值；分四段：【因子是什么】【当前状态解读】【对策略的意义】【风险与注意】；"
    "总字数280~420字，不要使用markdown表格，不要给具体买卖指令，结尾用一句话提示“仅为研究参考”。"
)

STRATEGY_SYSTEM = (
    "你是一名量化策略工程师。根据用户需求生成可直接运行的 Python 函数。"
    "严格要求：\n1) 只输出一个 ```python 代码块，里面必须定义 def generate_signals(df, params)，"
    "返回每日目标仓位 pd.Series（1 持有、0 空仓、-1 做空）。\n"
    "2) 只能使用 df 已有列、pd、np 与参数 params，禁止 import、禁止读写文件、禁止网络请求。\n"
    "3) 代码块之后用 3~5 行中文说明思路、适用行情与风险。\n"
    "4) 信号要考虑因子状态持续性，避免每日反复跳变（可用阈值或简单状态机）。"
)

COLUMN_DOC = (
    "df 列：date, open, high, low, close, volume, amount, turnover, ma5, ma10, ma20, ma60；"
    "因子原始值列 r_<id>，因子评分列 s_<id>（-100~100，正=偏多）；"
    "id 列表：ma_bias20, ma_slope20, mom20, rev5, macd_hist, rsi14, kdj_j, boll_pctb, "
    "atr_pct, volume_ratio, turnover, clv, amplitude"
)

EXAMPLE_STRATEGY = """```python
def generate_signals(df, params):
    # 中期动量向上 + 短期回踩 + 乖离未过热 = 顺势低吸
    hold = (df["s_mom20"] > 20) & (df["s_rev5"] > -40) & (df["s_ma_bias20"] > -60)
    return hold.astype(int)
```"""


def factor_messages(snapshot: dict, factor: dict) -> list[dict]:
    q = snapshot.get("quote", {})
    comp = snapshot.get("composite", {})
    payload = {
        "股票": f"{snapshot.get('name')}({snapshot.get('symbol')})",
        "最新价": q.get("price"),
        "日涨跌幅": f"{q.get('change_pct')}%",
        "数据日期": q.get("date"),
        "因子名称": factor.get("name"),
        "因子类别": factor.get("category"),
        "因子含义": factor.get("meaning"),
        "因子作用": factor.get("role"),
        "计算公式": factor.get("formula"),
        "当前原始值": factor.get("display"),
        "当前评分(-100~100)": factor.get("score"),
        "当前状态档位": factor.get("state"),
        "五档状态定义(由空到多)": factor.get("levels"),
        "近一年分位": f"{factor.get('pct_rank')}%",
        "近5日评分变化": factor.get("delta5"),
        "连续处于当前档天数": factor.get("duration"),
        "综合多因子评分": f"{comp.get('score')}（{comp.get('label')}）",
        "权重说明": factor.get("weight_note"),
    }
    return [
        {"role": "system", "content": FACTOR_SYSTEM},
        {
            "role": "user",
            "content": "请解读下面这个因子的当前状态：\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        },
    ]


def strategy_messages(requirement: str, symbol: str, name: str) -> list[dict]:
    return [
        {"role": "system", "content": STRATEGY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"标的：{name}({symbol})\n用户需求：{requirement}\n\n"
                f"{COLUMN_DOC}\n\n参考写法：\n{EXAMPLE_STRATEGY}"
            ),
        },
    ]


async def explain_factor_stream(cfg: dict, snapshot: dict, factor: dict) -> AsyncIterator[dict]:
    """产出 {'delta': str} / {'done': True, 'local': bool} 事件。"""
    if not configured(cfg):
        text = local_factor_explain(snapshot, factor)
        for i in range(0, len(text), 40):
            yield {"delta": text[i : i + 40]}
        yield {"done": True, "local": True}
        return
    try:
        async for chunk in stream_chat(cfg, factor_messages(snapshot, factor)):
            yield {"delta": chunk}
        yield {"done": True, "local": False}
    except Exception as e:
        yield {"delta": local_factor_explain(snapshot, factor), "error": str(e)}
        yield {"done": True, "local": True, "error": str(e)}


async def generate_strategy_stream(cfg: dict, requirement: str, symbol: str, name: str) -> AsyncIterator[dict]:
    if not configured(cfg):
        yield {"delta": local_strategy_hint(), "error": "未配置大模型 API Key", "local": True}
        yield {"done": True, "local": True, "error": "未配置大模型 API Key"}
        return
    try:
        async for chunk in stream_chat(cfg, strategy_messages(requirement, symbol, name)):
            yield {"delta": chunk}
        yield {"done": True, "local": False}
    except Exception as e:
        yield {"delta": f"生成失败：{e}", "error": str(e)}
        yield {"done": True, "local": False, "error": str(e)}
