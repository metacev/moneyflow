"""因子库：每个因子的元数据（含义/作用/公式/状态解读）与计算逻辑放在同一处，保证
界面上展示的解释与实际计算永远一致。

统一约定：
- 每个因子产出 score ∈ [-100, 100]，正值偏多、负值偏空（波动/活跃度类因子为相对强度）。
- bands = [-60, -20, 20, 60]，把 score 切成 5 档，对应 levels 里的 5 条状态解读。
- weight > 0 的因子参与“综合多因子评分”，weight = 0 的只做展示（它们不构成多空方向）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BANDS = [-60, -20, 20, 60]


def _clip100(s: pd.Series) -> pd.Series:
    return s.clip(-100, 100).fillna(0.0)


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _pct_score(s: pd.Series, window: int = 250) -> pd.Series:
    """按滚动分位数归一化到 [-100,100]，适合没有方向、只有强弱的指标。"""
    r = s.rolling(window, min_periods=40).rank(pct=True)
    return ((r - 0.5) * 200).fillna(0.0)


# --------------------------------------------------------------------------- #
# 各因子计算函数（输入为含 open/high/low/close/volume/turnover 的 DataFrame）
# --------------------------------------------------------------------------- #
def calc_ma_bias(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    ma20 = df["close"].rolling(20, min_periods=20).mean()
    bias = (df["close"] / ma20 - 1) * 100
    return bias, _clip100(-bias * 10)


def calc_ma_slope(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    ma20 = df["close"].rolling(20, min_periods=20).mean()
    slope = (ma20 / ma20.shift(10) - 1) * 100
    return slope, _clip100(slope * 8)


def calc_mom20(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    mom = (df["close"] / df["close"].shift(20) - 1) * 100
    return mom, _clip100(mom * 5)


def calc_rev5(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    rev = (df["close"] / df["close"].shift(5) - 1) * 100
    return rev, _clip100(-rev * 10)


def calc_macd(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    dif = _ema(df["close"], 12) - _ema(df["close"], 26)
    dea = _ema(dif, 9)
    hist = (dif - dea) * 2 / df["close"] * 100
    return hist, _clip100(hist * 80)


def calc_rsi(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    avg_up = up.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_dn = down.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_up / avg_dn.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.fillna(50)
    return rsi, _clip100(-(rsi - 50) * 2.5)


def calc_kdj(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    low9 = df["low"].rolling(9, min_periods=9).min()
    high9 = df["high"].rolling(9, min_periods=9).max()
    rsv = (df["close"] - low9) / (high9 - low9).replace(0, np.nan) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return j, _clip100(-(j - 50) * 1.6)


def calc_boll(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    mid = df["close"].rolling(20, min_periods=20).mean()
    std = df["close"].rolling(20, min_periods=20).std()
    upper, lower = mid + 2 * std, mid - 2 * std
    pctb = (df["close"] - lower) / (upper - lower).replace(0, np.nan)
    return pctb, _clip100(-(pctb - 0.5) * 180)


def calc_atr(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    pc = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_pct = atr / df["close"] * 100
    return atr_pct, _pct_score(atr_pct)


def calc_volume_ratio(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    v5 = df["volume"].rolling(5, min_periods=5).mean()
    v20 = df["volume"].rolling(20, min_periods=20).mean()
    vr = v5 / v20.replace(0, np.nan)
    return vr, _clip100((vr - 1) * 120)


def calc_turnover(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if "turnover" not in df.columns:
        df = df.assign(turnover=0.0)
    t = df["turnover"].astype(float)
    return t, _pct_score(t)


def calc_clv(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    return clv.fillna(0), _clip100(clv * 100)


# --------------------------------------------------------------------------- #
# 因子元数据
# --------------------------------------------------------------------------- #
FACTORS: list[dict] = [
    {
        "id": "ma_bias20",
        "name": "20日乖离率",
        "short": "乖离率",
        "category": "趋势",
        "unit": "%",
        "weight": 12,
        "cores": 12,
        "meaning": "收盘价相对20日均线的偏离百分比，衡量价格离“中期平均成本”有多远。",
        "role": "判断短期是否涨过头/跌过头。正乖离过大说明追高风险高、回调概率上升；负乖离过大说明超跌、存在修复动力。属于均值回归信号。",
        "formula": "(收盘价 - MA20) / MA20 × 100%",
        "levels": ["超涨·回调风险", "偏热·追高需谨慎", "中性·贴合均线", "偏冷·修复机会", "超跌·反弹机会"],
        "weight_note": "权重12：反向（超涨看空、超跌看多）",
        "compute": calc_ma_bias,
        "fmt": "{:.2f}%",
    },
    {
        "id": "ma_slope20",
        "name": "均线趋势斜率",
        "short": "趋势斜率",
        "category": "趋势",
        "unit": "%",
        "weight": 14,
        "meaning": "20日均线过去10个交易日的涨幅，反映中期趋势的方向与力度。",
        "role": "趋势是否成立的第一判据。斜率向上说明中期资金在抬升成本，趋势策略胜率更高；走平代表震荡，趋势策略容易被打脸。",
        "formula": "(MA20 / MA20.10日前 - 1) × 100%",
        "levels": ["下行趋势", "弱势下行", "走平震荡", "温和上行", "强势上行"],
        "weight_note": "权重14：正向（趋势向上看多）",
        "compute": calc_ma_slope,
        "fmt": "{:+.2f}%",
    },
    {
        "id": "mom20",
        "name": "20日动量",
        "short": "20日动量",
        "category": "动量",
        "unit": "%",
        "weight": 16,
        "meaning": "过去20个交易日的累计涨跌幅，是最经典的动量因子。",
        "role": "捕捉“强者恒强”。A股中期动量有效，但过高时需警惕拥挤；为负时代表资金持续流出，不宜逆势做多。",
        "formula": "(收盘价 / 20日前收盘价 - 1) × 100%",
        "levels": ["强空动量", "弱势动量", "动量中性", "偏多动量", "强多动量"],
        "weight_note": "权重16：正向（涨得越强越看多）",
        "compute": calc_mom20,
        "fmt": "{:+.2f}%",
    },
    {
        "id": "rev5",
        "name": "5日短期反转",
        "short": "短期反转",
        "category": "动量",
        "unit": "%",
        "weight": 8,
        "meaning": "过去5个交易日的涨跌幅，刻画短线情绪与超买超卖。",
        "role": "A股短线反转效应显著：急涨后容易回吐，急跌后常有反抽。与20日动量组合，可以识别“中期趋势+短期回踩”的买点。",
        "formula": "(收盘价 / 5日前收盘价 - 1) × 100%，评分取反",
        "levels": ["急涨·兑现压力", "偏强·短线过热", "震荡", "偏弱·超跌", "急跌·反弹契机"],
        "weight_note": "权重8：反向（急涨看空、急跌看多）",
        "compute": calc_rev5,
        "fmt": "{:+.2f}%",
    },
    {
        "id": "macd_hist",
        "name": "MACD 柱能量",
        "short": "MACD能量",
        "category": "趋势",
        "unit": "%",
        "weight": 14,
        "meaning": "DIF 与 DEA 之差的2倍（占股价百分比），即MACD柱，代表多空动能的边际变化。",
        "role": "柱体由负转正=金叉动能启动，持续放大=趋势加速，缩短=动能衰竭。比单纯看金叉更早反映拐点。",
        "formula": "2×(DIF - DEA) / 收盘价 × 100%，DIF=EMA12-EMA26，DEA=EMA9(DIF)",
        "levels": ["空头动能强", "空头动能减弱", "多空平衡", "多头动能", "多头动能强"],
        "weight_note": "权重14：正向（红柱放大看多）",
        "compute": calc_macd,
        "fmt": "{:+.3f}%",
    },
    {
        "id": "rsi14",
        "name": "RSI 相对强弱",
        "short": "RSI14",
        "category": "摆动",
        "unit": "",
        "weight": 10,
        "meaning": "14日内上涨力量占全部波动的比例，取值0~100，衡量多空力量对比。",
        "role": "经典超买超卖指标：>70 往往对应短线过热，<30 对应超跌。单边强趋势中RSI会长期高位钝化，需结合趋势因子使用。",
        "formula": "RSI = 100 - 100/(1+平均涨幅/平均跌幅)，Wilder平滑14日",
        "levels": ["超买·回落风险", "偏强·接近超买", "多空均衡", "偏弱·接近超卖", "超卖·反弹机会"],
        "weight_note": "权重10：反向（超买看空、超卖看多）",
        "compute": calc_rsi,
        "fmt": "{:.1f}",
    },
    {
        "id": "kdj_j",
        "name": "KDJ 的 J 值",
        "short": "KDJ-J",
        "category": "摆动",
        "unit": "",
        "weight": 6,
        "meaning": "KDJ 中 J = 3K - 2D，是最敏感的短线摆动值，可超出0~100区间。",
        "role": "J>100 表示短线极度强势/超买，J<0 表示极度弱势/超卖，常用于捕捉短线拐点，噪音相对较大，权重给得较低。",
        "formula": "RSV=(C-L9)/(H9-L9)×100，K=RSV的EMA3，D=K的EMA3，J=3K-2D",
        "levels": ["J值过热", "J值偏高", "J值中性", "J值偏低", "J值超卖"],
        "weight_note": "权重6：反向（过热看空、超卖看多）",
        "compute": calc_kdj,
        "fmt": "{:.1f}",
    },
    {
        "id": "boll_pctb",
        "name": "布林带 %B",
        "short": "布林%B",
        "category": "波动",
        "unit": "",
        "weight": 8,
        "meaning": "收盘价在布林带（20日±2倍标准差）中的相对位置：0=下轨，0.5=中轨，1=上轨。",
        "role": "衡量价格在统计通道中的位置。>1 突破上轨属强势但易回归，<0 跌破下轨属弱势但常反抽；配合带宽收缩可识别变盘。",
        "formula": "%B = (收盘价 - 下轨) / (上轨 - 下轨)",
        "levels": ["触及上轨·超买", "上轨区·偏强", "中轨附近", "下轨区·偏弱", "触及下轨·超卖"],
        "weight_note": "权重8：反向（触上轨看空、触下轨看多）",
        "compute": calc_boll,
        "fmt": "{:.2f}",
    },
    {
        "id": "atr_pct",
        "name": "ATR 波动率",
        "short": "ATR波动",
        "category": "风险",
        "unit": "%",
        "weight": 0,
        "meaning": "14日平均真实波幅占股价的百分比，衡量日常波动大小（不含方向）。",
        "role": "决定仓位与止损宽度的核心风险参数。波动放大时同样仓位风险翻倍，应缩小持仓或放宽止损；波动收敛常预示变盘。",
        "formula": "TR=max(H-L, |H-昨C|, |L-昨C|)，ATR=TR的14日Wilder平滑，ATR%=ATR/收盘价×100",
        "levels": ["低波动·安静", "波动偏低", "波动正常", "波动偏高", "高波动·风险大"],
        "weight_note": "不参与多空评分：仅用于风险控制",
        "compute": calc_atr,
        "fmt": "{:.2f}%",
    },
    {
        "id": "volume_ratio",
        "name": "量比（5日/20日）",
        "short": "量比",
        "category": "量能",
        "unit": "",
        "weight": 0,
        "meaning": "5日均量与20日均量之比，刻画近期资金参与度的相对变化。",
        "role": "量在价先。放量突破可信度更高，缩量上涨多为存量博弈；但放量下跌也代表恐慌，需要结合价格方向解读。",
        "formula": "5日均量 / 20日均量",
        "levels": ["缩量·人气低迷", "量能偏弱", "量能平稳", "温和放量", "显著放量"],
        "weight_note": "不参与多空评分：放量本身无方向",
        "compute": calc_volume_ratio,
        "fmt": "{:.2f}",
    },
    {
        "id": "turnover",
        "name": "换手率",
        "short": "换手率",
        "category": "量能",
        "unit": "%",
        "weight": 0,
        "meaning": "当日成交量占流通股本的比例，衡量筹码交换的活跃程度。",
        "role": "低换手说明关注度低、流动性差；换手骤升常伴随题材炒作或筹码松动。A股2%~5%属健康活跃，>10%多为博弈激烈。",
        "formula": "成交量 / 流通股本 × 100%",
        "levels": ["冰点·无人问津", "清淡", "正常", "活跃", "过热·拥挤"],
        "weight_note": "不参与多空评分：仅反映活跃度",
        "compute": calc_turnover,
        "fmt": "{:.2f}%",
    },
    {
        "id": "clv",
        "name": "收盘强度 CLV",
        "short": "收盘强度",
        "category": "情绪",
        "unit": "",
        "weight": 8,
        "meaning": "收盘价在当日振幅中的位置，取值-1~1，反映尾盘多空谁在主导。",
        "role": "收在最高附近(接近1)说明买盘愿意持股过夜，次日续强概率高；收在最低附近(接近-1)说明抛压主导，常预示低开。",
        "formula": "((C-L) - (H-C)) / (H-L)",
        "levels": ["抛压主导", "空方占优", "多空拉锯", "多方占优", "买盘强势"],
        "weight_note": "权重8：正向（收得越高越看多）",
        "compute": calc_clv,
        "fmt": "{:+.2f}",
    },
    {
        "id": "amplitude",
        "name": "20日振幅",
        "short": "振幅",
        "category": "风险",
        "unit": "%",
        "weight": 0,
        "meaning": "最近20个交易日 (最高-最低)/昨收 的均值，衡量价格波动区间宽度。",
        "role": "振幅扩大说明多空分歧加剧，短线机会与风险同时放大；振幅收窄往往是大行情前的蓄势。",
        "formula": "mean((H-L)/昨C, 20日) × 100",
        "levels": ["窄幅横盘", "振幅偏窄", "振幅正常", "振幅放大", "剧烈震荡"],
        "weight_note": "不参与多空评分：仅反映波动区间",
        "compute": lambda df: (
            ((df["high"] - df["low"]) / df["close"].shift(1).replace(0, np.nan) * 100)
            .rolling(20, min_periods=10).mean(),
            _pct_score(((df["high"] - df["low"]) / df["close"].shift(1).replace(0, np.nan) * 100).rolling(20, min_periods=10).mean()),
        ),
        "fmt": "{:.2f}%",
    },
]

FACTOR_MAP = {f["id"]: f for f in FACTORS}
DIRECTIONAL_WEIGHTS = {f["id"]: f["weight"] for f in FACTORS if f["weight"] > 0}


def level_index(score: float) -> int:
    for i, b in enumerate(BANDS):
        if score < b:
            return i
    return 4
