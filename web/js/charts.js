/* 图表层：全部基于本地打包的 ECharts，无外部依赖 */
const C = {
  up: "#f6465d",
  down: "#16c784",
  text: "#e9eefb",
  muted: "#93a2bb",
  dim: "#64748b",
  line: "rgba(148,163,184,.14)",
  accent: "#38bdf8",
  gold: "#fbbf24",
  purple: "#a78bfa",
  mono: "JetBrains Mono, Consolas, monospace",
  palette: ["#38bdf8", "#fbbf24", "#a78bfa", "#f6465d", "#16c784", "#fb923c", "#e879f9", "#2dd4bf", "#93c5fd", "#facc15", "#f472b6", "#4ade80"],
};

const Charts = {
  kline: null,
  trend: null,
  gauge: null,
  radar: null,
  equity: null,
  dd: null,
  trendIds: ["mom20", "ma_slope20", "macd_hist", "rsi14"],

  _init(el, inst) {
    if (!el) return null;
    if (inst && !inst.isDisposed()) return inst;
    const chart = echarts.init(el, null, { renderer: "canvas" });
    return chart;
  },

  initDashboard(snap, factorHistory) {
    this.initKline(snap);
    this.initGauge(snap);
    this.initRadar(snap);
    this.initTrend(factorHistory);
  },

  /* ---------------- K线 ---------------- */
  initKline(snap) {
    const el = document.getElementById("chart-price");
    this.kline = this._init(el, this.kline);
    if (!this.kline) return;
    const k = snap.kline;
    this._setKlineOption(k);
    this.kline.setOption({ xAxis: [{ data: k.dates }, { data: k.dates }] });
  },

  _setKlineOption(k) {
    const volColors = k.ohlc.map((d) => (d[1] >= d[0] ? "rgba(246,70,93,.4)" : "rgba(22,199,132,.4)"));
    this.kline.setOption(
      {
        animation: false,
        backgroundColor: "transparent",
        textStyle: { fontFamily: C.mono },
        grid: [
          { left: 56, right: 70, top: 30, height: "58%" },
          { left: 56, right: 70, top: "76%", height: "12%" },
        ],
        axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: "#1e293b", borderColor: "transparent" } },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "cross", crossStyle: { color: C.dim } },
          backgroundColor: "rgba(10,16,30,.95)",
          borderColor: "rgba(148,163,184,.25)",
          textStyle: { color: C.text, fontSize: 11, fontFamily: C.mono },
          formatter(params) {
            const p = params.find((x) => x.seriesName === "K线");
            if (!p) return "";
            const [o, c, l, h] = p.data.slice(1);
            const chg = o ? ((c / o - 1) * 100).toFixed(2) : "0";
            return `<b>${p.axisValue}</b><br/>开 ${o}　收 ${c}<br/>高 ${h}　低 ${l}<br/>涨跌 ${chg}%`;
          },
        },
        xAxis: [
          {
            type: "category",
            data: k.dates,
            gridIndex: 0,
            boundaryGap: true,
            axisLine: { lineStyle: { color: C.line } },
            axisTick: { show: false },
            axisLabel: { show: false },
            splitLine: { show: false },
          },
          {
            type: "category",
            data: k.dates,
            gridIndex: 1,
            boundaryGap: true,
            axisLine: { lineStyle: { color: C.line } },
            axisTick: { show: false },
            axisLabel: { color: C.dim, fontSize: 9, hideOverlap: true },
            splitLine: { show: false },
          },
        ],
        yAxis: [
          {
            scale: true,
            gridIndex: 0,
            position: "right",
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: C.dim, fontSize: 10 },
            splitLine: { lineStyle: { color: C.line } },
          },
          {
            gridIndex: 1,
            position: "right",
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { show: false },
            splitLine: { show: false },
            splitNumber: 2,
          },
        ],
        dataZoom: [
          { type: "inside", xAxisIndex: [0, 1], start: 55, end: 100 },
          {
            type: "slider",
            xAxisIndex: [0, 1],
            bottom: 2,
            height: 14,
            start: 55,
            end: 100,
            borderColor: "transparent",
            backgroundColor: "rgba(148,163,184,.08)",
            fillerColor: "rgba(56,189,248,.16)",
            handleStyle: { color: C.accent },
            moveHandleStyle: { color: "rgba(56,189,248,.4)" },
            textStyle: { color: C.dim, fontSize: 9 },
            dataBackground: { lineStyle: { color: C.dim, opacity: 0.3 }, areaStyle: { color: C.dim, opacity: 0.08 } },
          },
        ],
        series: [
          {
            name: "K线",
            type: "candlestick",
            data: k.ohlc,
            itemStyle: { color: C.up, color0: C.down, borderColor: C.up, borderColor0: C.down },
          },
          { name: "MA5", type: "line", data: k.ma5, smooth: true, showSymbol: false, lineStyle: { width: 1, color: C.gold, opacity: 0.85 } },
          { name: "MA20", type: "line", data: k.ma20, smooth: true, showSymbol: false, lineStyle: { width: 1, color: C.accent, opacity: 0.9 } },
          { name: "MA60", type: "line", data: k.ma60, smooth: true, showSymbol: false, lineStyle: { width: 1, color: C.purple, opacity: 0.8 } },
          {
            name: "成交量",
            type: "bar",
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: k.volume.map((v, i) => ({ value: v, itemStyle: { color: volColors[i] } })),
            barWidth: "60%",
          },
        ],
      },
      true
    );
  },

  updateLastBar(bar, volume, date) {
    if (!this.kline) return;
    const opt = this.kline.getOption();
    const ohlc = opt.series[0].data;
    if (ohlc && ohlc.length) ohlc[ohlc.length - 1] = bar;
    const vol = opt.series[4].data;
    if (vol && vol.length) {
      vol[vol.length - 1] = {
        value: volume,
        itemStyle: { color: bar[1] >= bar[0] ? "rgba(246,70,93,.4)" : "rgba(22,199,132,.4)" },
      };
    }
    this.kline.setOption({ series: [{ data: ohlc }, {}, {}, {}, { data: vol }] });
  },

  /* ---------------- 因子走势 ---------------- */
  initTrend(history) {
    const el = document.getElementById("chart-factor-trend");
    this.trend = this._init(el, this.trend);
    if (!this.trend) return;
    this.setTrend(history);
  },

  setTrend(history) {
    if (!this.trend || !history) return;
    const ids = this.trendIds;
    const series = ids.map((id, i) => ({
      name: id,
      type: "line",
      data: history.series[id] || [],
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 1.6, color: C.palette[i % C.palette.length], opacity: 0.95 },
      emphasis: { focus: "series" },
    }));
    this.trend.setOption(
      {
        animation: false,
        backgroundColor: "transparent",
        textStyle: { fontFamily: C.mono },
        grid: { left: 46, right: 16, top: 18, bottom: 40 },
        tooltip: {
          trigger: "axis",
          backgroundColor: "rgba(10,16,30,.95)",
          borderColor: "rgba(148,163,184,.25)",
          textStyle: { color: C.text, fontSize: 11, fontFamily: C.mono },
        },
        legend: {
          top: 0,
          right: 6,
          textStyle: { color: C.muted, fontSize: 10 },
          itemWidth: 14,
          itemHeight: 3,
        },
        xAxis: {
          type: "category",
          data: history.dates,
          axisLine: { lineStyle: { color: C.line } },
          axisTick: { show: false },
          axisLabel: { color: C.dim, fontSize: 9, hideOverlap: true },
        },
        yAxis: {
          min: -100,
          max: 100,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: C.dim, fontSize: 9 },
          splitLine: { lineStyle: { color: C.line } },
        },
        dataZoom: [{ type: "inside", start: 40, end: 100 }],
        series,
      },
      true
    );
  },

  updateTrendLast(values, date) {
    if (!this.trend) return;
    const opt = this.trend.getOption();
    const series = opt.series.map((s) => {
      const data = s.data.slice();
      if (data.length) data[data.length - 1] = values[s.name];
      return { data };
    });
    this.trend.setOption({ series });
  },

  /* ---------------- 仪表盘 ---------------- */
  initGauge(snap) {
    const el = document.getElementById("chart-gauge");
    this.gauge = this._init(el, this.gauge);
    if (!this.gauge) return;
    const comp = snap.composite;
    this.gauge.setOption({
      animationDuration: 700,
      series: [
        {
          type: "gauge",
          min: -100,
          max: 100,
          startAngle: 210,
          endAngle: -30,
          radius: "92%",
          center: ["50%", "58%"],
          progress: { show: false },
          axisLine: {
            lineStyle: {
              width: 12,
              color: [
                [0.2, "rgba(22,199,132,.85)"],
                [0.4, "rgba(74,222,128,.6)"],
                [0.6, "rgba(100,116,139,.65)"],
                [0.8, "rgba(251,113,133,.65)"],
                [1, "rgba(246,70,93,.9)"],
              ],
            },
          },
          axisTick: { show: false },
          splitLine: { distance: 4, length: 7, lineStyle: { color: "rgba(148,163,184,.35)", width: 1 } },
          axisLabel: { distance: -4, color: C.dim, fontSize: 9, fontFamily: C.mono },
          pointer: { width: 3, length: "52%", itemStyle: { color: "#cfe9ff" } },
          anchor: { show: true, size: 9, itemStyle: { color: "#cfe9ff", borderColor: "#0a1120", borderWidth: 2 } },
          detail: {
            valueAnimation: true,
            offsetCenter: [0, "42%"],
            fontSize: 24,
            fontWeight: 700,
            fontFamily: C.mono,
            color: C.text,
            formatter: (v) => (v > 0 ? "+" : "") + v.toFixed(1),
          },
          title: { show: false },
          data: [{ value: comp.score, name: "综合评分" }],
        },
      ],
    });
    this.setGauge(comp.score);
  },

  setGauge(score) {
    if (!this.gauge) return;
    this.gauge.setOption({ series: [{ data: [{ value: score, name: "综合评分" }] }] });
  },

  /* ---------------- 雷达 ---------------- */
  initRadar(snap) {
    const el = document.getElementById("chart-radar");
    this.radar = this._init(el, this.radar);
    if (!this.radar) return;
    const dir = snap.factors.filter((f) => f.weight > 0);
    this.radar.setOption({
      animationDuration: 600,
      backgroundColor: "transparent",
      radar: {
        center: ["50%", "52%"],
        radius: "62%",
        splitNumber: 4,
        axisName: { color: C.muted, fontSize: 9.5 },
        splitLine: { lineStyle: { color: C.line } },
        splitArea: { areaStyle: { color: ["rgba(148,163,184,.02)", "rgba(148,163,184,.05)"] } },
        axisLine: { lineStyle: { color: C.line } },
        indicator: dir.map((f) => ({ name: f.short, max: 100 })),
      },
      series: [
        {
          type: "radar",
          symbol: "circle",
          symbolSize: 3,
          data: [
            {
              value: dir.map((f) => (f.score + 100) / 2),
              name: "因子评分",
              areaStyle: { color: "rgba(56,189,248,.18)" },
              lineStyle: { color: "rgba(56,189,248,.7)", width: 1.2 },
              itemStyle: { color: C.accent },
            },
          ],
        },
      ],
    });
  },

  setRadar(factors) {
    if (!this.radar) return;
    const dir = factors.filter((f) => f.weight > 0);
    this.radar.setOption({
      radar: { indicator: dir.map((f) => ({ name: f.short, max: 100 })) },
      series: [{ data: [{ value: dir.map((f) => (f.score + 100) / 2) }] }],
    });
  },

  /* ---------------- 回测 ---------------- */
  initEquity() {
    const el = document.getElementById("chart-equity");
    this.equity = this._init(el, this.equity);
    return this.equity;
  },

  setEquity(result) {
    const el = document.getElementById("chart-equity");
    if (!this.equity) this.equity = this._init(el, null);
    if (!this.equity) return;
    this.equity.setOption(
      {
        animationDuration: 500,
        backgroundColor: "transparent",
        textStyle: { fontFamily: C.mono },
        grid: { left: 58, right: 58, top: 16, bottom: 30 },
        tooltip: {
          trigger: "axis",
          backgroundColor: "rgba(10,16,30,.95)",
          borderColor: "rgba(148,163,184,.25)",
          textStyle: { color: C.text, fontSize: 11, fontFamily: C.mono },
          valueFormatter: (v) => Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 0 }),
        },
        legend: { top: 0, right: 4, textStyle: { color: C.muted, fontSize: 10 }, itemWidth: 14, itemHeight: 3 },
        xAxis: {
          type: "category",
          data: result.dates,
          axisLine: { lineStyle: { color: C.line } },
          axisTick: { show: false },
          axisLabel: { color: C.dim, fontSize: 9, hideOverlap: true },
        },
        yAxis: [
          {
            scale: true,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: C.dim, fontSize: 9, formatter: (v) => (v >= 10000 ? (v / 10000).toFixed(1) + "万" : v) },
            splitLine: { lineStyle: { color: C.line } },
          },
        ],
        dataZoom: [{ type: "inside", start: 40, end: 100 }],
        series: [
          {
            name: "策略",
            type: "line",
            data: result.equity,
            showSymbol: false,
            lineStyle: { width: 1.8, color: C.up },
            areaStyle: {
              color: {
                type: "linear", x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [{ offset: 0, color: "rgba(246,70,93,.22)" }, { offset: 1, color: "rgba(246,70,93,0)" }],
              },
            },
          },
          {
            name: "买入持有",
            type: "line",
            data: result.benchmark,
            showSymbol: false,
            lineStyle: { width: 1.3, color: C.dim, type: "dashed" },
          },
        ],
      },
      true
    );
  },

  setDrawdown(result) {
    const el = document.getElementById("chart-drawdown");
    if (!this.dd) this.dd = this._init(el, null);
    if (!this.dd) return;
    this.dd.setOption(
      {
        animationDuration: 400,
        backgroundColor: "transparent",
        textStyle: { fontFamily: C.mono },
        grid: { left: 58, right: 58, top: 8, bottom: 22 },
        tooltip: {
          trigger: "axis",
          backgroundColor: "rgba(10,16,30,.95)",
          borderColor: "rgba(148,163,184,.25)",
          textStyle: { color: C.text, fontSize: 11, fontFamily: C.mono },
          valueFormatter: (v) => v + "%",
        },
        xAxis: {
          type: "category",
          data: result.dates,
          axisLine: { lineStyle: { color: C.line } },
          axisTick: { show: false },
          axisLabel: { color: C.dim, fontSize: 9, hideOverlap: true },
        },
        yAxis: {
          max: 0,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: C.dim, fontSize: 9, formatter: "{value}%" },
          splitLine: { lineStyle: { color: C.line } },
        },
        series: [
          {
            name: "回撤",
            type: "line",
            data: result.drawdown,
            showSymbol: false,
            lineStyle: { width: 1, color: C.down },
            areaStyle: { color: "rgba(22,199,132,.2)" },
          },
        ],
      },
      true
    );
  },

  resizeAll() {
    [this.kline, this.trend, this.gauge, this.radar, this.equity, this.dd].forEach((c) => {
      if (c && !c.isDisposed()) c.resize();
    });
  },
};
