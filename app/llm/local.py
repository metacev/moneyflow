"""离线本地解读：没有配置大模型 Key 时，用因子元数据 + 实时计算结果生成结构化解读。"""
from __future__ import annotations

from app.factors.library import FACTOR_MAP


def _rank_text(pct: float | None) -> str:
    if pct is None:
        return "历史分位暂缺"
    p = float(pct)
    if p >= 85:
        return f"处于近一年高位（{p:.0f}% 分位），读数偏高"
    if p <= 15:
        return f"处于近一年低位（{p:.0f}% 分位），读数偏低"
    return f"位于近一年中段（{p:.0f}% 分位）"


def local_factor_explain(snapshot: dict, factor: dict) -> str:
    name = snapshot.get("name", "")
    sym = snapshot.get("symbol", "")
    q = snapshot.get("quote", {})
    comp = snapshot.get("composite", {})
    levels = factor.get("levels") or []
    lvl = int(factor.get("level") or 0)
    next_hint = ""
    if lvl < 4 and lvl + 1 < len(levels):
        next_hint = f"若继续向{levels[min(lvl + 1, 4)]}方向演化，说明{('多头' if lvl >= 2 else '空头')}动能在增强。"

    duration = factor.get("duration") or 0
    delta = factor.get("delta5") or 0
    if delta > 0:
        trend = f"近5日评分上升 {delta:+.1f}，因子在改善"
    elif delta < 0:
        trend = f"近5日评分下降 {delta:+.1f}，因子在走弱"
    else:
        trend = "近5日评分基本持平"

    weight = factor.get("weight") or 0
    if weight > 0:
        role_line = f"该因子参与综合评分，权重 {weight}（{factor.get('weight_note','')}），当前为综合评分贡献约 {factor.get('score',0) * weight / max(int(comp.get('total_weight') or 1), 1):.1f} 分。"
    else:
        role_line = f"该因子不参与多空方向评分（{factor.get('weight_note','仅作辅助观察')}），用于判断{'风险' if factor.get('category')=='风险' else '活跃度'}状态。"

    return (
        f"【因子是什么】\n{factor.get('name')}（{factor.get('category')}类）衡量{factor.get('meaning')}"
        f"计算方式：{factor.get('formula')}。\n\n"
        f"【当前状态解读】\n{sym} {name} 最新价 {q.get('price')}（{q.get('change_pct')}%），"
        f"{factor.get('name')} 当前读数 {factor.get('display')}，评分 {factor.get('score')}，"
        f"处于「{factor.get('state')}」档（五档：{' / '.join(levels)}），"
        f"{_rank_text(factor.get('pct_rank'))}；{trend}；已连续 {duration} 个交易日处于该档。"
        f"{next_hint}\n\n"
        f"【对策略的意义】\n{factor.get('role')}\n{role_line}"
        f"综合多因子评分目前为 {comp.get('score')}（{comp.get('label')}）：{comp.get('desc')}。\n\n"
        f"【风险与注意】\n单一因子会受样本期、参数与行情风格影响，"
        f"{'当前数据为模拟行情，仅用于验证逻辑。' if snapshot.get('source', {}).get('simulated') else '请在真实行情中复核信号稳定性。'}"
        f"建议结合趋势与量能因子交叉验证，并以回测结果为准。\n\n"
        f"仅为研究参考，不构成投资建议。"
    )


def local_strategy_hint() -> str:
    tips = [
        f"- {f['name']}（{f['id']}）：{f['meaning']}" for f in list(FACTOR_MAP.values())[:4]
    ]
    return (
        "未配置大模型 API Key，无法自动生成策略。你可以：\n"
        "1. 在【设置】中填入任意 OpenAI 兼容接口的 Base URL / Model / API Key（如 DeepSeek、通义千问、智谱）；\n"
        "2. 直接使用内置模板（双均线、MACD、RSI反转、布林回归、多因子共振）；\n"
        "3. 在【自定义代码】里编写 generate_signals(df, params)。\n\n"
        "可用因子示例：\n" + "\n".join(tips)
    )
