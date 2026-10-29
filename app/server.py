"""FastAPI 服务：REST + WebSocket 实时推送 + 静态前端。"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config as cfgmod
from app.config import SYMBOL_NAMES, load_config, public_config, save_config, symbol_name
from app.datasource.manager import DataSourceManager
from app.factors.library import FACTORS
from app.factors.engine import compute_frame
from app.llm import client as llm
from app.market import MarketHub
from app.strategy.engine import run_backtest
from app.strategy.templates import DEFAULT_CODE, TEMPLATES, generate_signals, StrategyError

WEB_DIR = cfgmod.resource_dir() / "web"
VERSION = "0.1.0"

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    manager = DataSourceManager(cfg)
    hub = MarketHub(cfg, manager)
    state.update({"cfg": cfg, "manager": manager, "hub": hub})
    hub.start()
    try:
        yield
    finally:
        await hub.stop()


app = FastAPI(title="QuantFactorLab", version=VERSION, lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/api/status")
async def status():
    cfg, manager, hub = state["cfg"], state["manager"], state["hub"]
    return {
        "version": VERSION,
        "llm_configured": llm.configured(cfg),
        "llm_model": cfg["llm"].get("model"),
        "data": manager.meta(),
        "hub": hub.status(),
        "market_open": __import__("app.datasource.akshare_source", fromlist=["is_trading_time"]).is_trading_time(),
        "server_time": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/config")
async def get_config():
    return public_config(state["cfg"])


@app.post("/api/config")
async def post_config(patch: dict):
    cfg = state["cfg"]
    merged = cfgmod._deep_merge(cfg, patch or {})
    saved = save_config(merged)
    state["cfg"] = saved
    manager: DataSourceManager = state["manager"]
    manager.cfg = saved
    manager.reload()
    hub: MarketHub = state["hub"]
    hub.cfg = saved
    hub.tick_interval = float(saved.get("tick_interval", 2.0))
    hub.active_symbol = saved.get("active_symbol") or saved["symbols"][0]
    hub.base_frames.clear()
    hub.metas.clear()
    hub.snap_meta.clear()
    hub.sim.clear()
    return {"ok": True, "config": public_config(saved), "data": manager.meta()}


@app.get("/api/symbols")
async def get_symbols():
    cfg = state["cfg"]
    codes = list(dict.fromkeys(list(cfg.get("symbols", [])) + list(SYMBOL_NAMES.keys())))
    return {
        "active": state["hub"].active_symbol,
        "items": [{"code": c, "name": symbol_name(c)} for c in codes],
    }


@app.get("/api/snapshot")
async def snapshot(symbol: str | None = None, refresh: bool = False):
    hub: MarketHub = state["hub"]
    sym = (symbol or hub.active_symbol).strip()
    if not sym.isdigit() or len(sym) != 6:
        raise HTTPException(400, "股票代码需为6位数字")
    if refresh:
        hub.refresh(sym)
    try:
        return await asyncio.to_thread(hub.snapshot, sym)
    except Exception as e:
        raise HTTPException(500, f"加载 {sym} 行情失败：{e}")


@app.get("/api/factor-library")
async def factor_library():
    keys = ["id", "name", "short", "category", "unit", "weight", "weight_note", "meaning", "role", "formula", "levels"]
    lib = [{k: f[k] for k in keys} for f in FACTORS]
    return {
        "factors": lib,
        "bands": [-60, -20, 20, 60],
        "categories": sorted({f["category"] for f in FACTORS}),
        "composite_formula": "(Σ 评分×权重) / Σ权重，仅统计有方向的因子",
        "total_weight": sum(f["weight"] for f in FACTORS if f["weight"] > 0),
    }


@app.get("/api/strategies")
async def strategies():
    out = []
    for t in TEMPLATES:
        item = {k: t[k] for k in ("id", "name", "desc", "params")}
        if t["id"] == "custom":
            item["default_code"] = DEFAULT_CODE
        out.append(item)
    return {"items": out, "defaults": state["cfg"].get("backtest", {})}


@app.post("/api/backtest")
async def backtest(req: dict):
    hub: MarketHub = state["hub"]
    cfg = state["cfg"]
    symbol = str(req.get("symbol") or hub.active_symbol)
    strategy = str(req.get("strategy") or "dual_ma")
    params = req.get("params") or {}
    conf = {**cfg.get("backtest", {}), **(req.get("settings") or {})}

    def _run():
        frame = hub.frame(symbol)
        sig = generate_signals(strategy, frame, params)
        result = run_backtest(
            frame,
            sig,
            initial_cash=float(conf.get("initial_cash", 100000)),
            fee_rate=float(conf.get("fee_rate", 0.0003)),
            slippage=float(conf.get("slippage", 0.0002)),
            allow_short=bool(conf.get("allow_short", False)),
        )
        result["symbol"] = symbol
        result["name"] = symbol_name(symbol)
        result["strategy"] = strategy
        result["source"] = hub.metas.get(symbol, {})
        return result

    try:
        return await asyncio.to_thread(_run)
    except StrategyError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"回测失败：{e}")


def _sse(gen) -> StreamingResponse:
    async def stream():
        async for ev in gen:
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/llm/explain")
async def llm_explain(req: dict):
    hub: MarketHub = state["hub"]
    cfg = state["cfg"]
    symbol = str(req.get("symbol") or hub.active_symbol)
    fid = str(req.get("factor_id") or "")
    try:
        snap = await asyncio.to_thread(hub.snapshot, symbol)
    except Exception as e:
        raise HTTPException(500, f"读取行情失败：{e}")
    factor = next((f for f in snap["factors"] if f["id"] == fid), None)
    if factor is None:
        raise HTTPException(404, f"未知因子 {fid}")
    return _sse(llm.explain_factor_stream(cfg, snap, factor))


@app.post("/api/llm/strategy")
async def llm_strategy(req: dict):
    hub: MarketHub = state["hub"]
    cfg = state["cfg"]
    symbol = str(req.get("symbol") or hub.active_symbol)
    requirement = str(req.get("requirement") or "").strip()
    if len(requirement) < 4:
        raise HTTPException(400, "请描述策略需求（至少4个字）")
    return _sse(llm.generate_strategy_stream(cfg, requirement, symbol, symbol_name(symbol)))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    hub: MarketHub = state["hub"]
    await ws.accept()
    hub.clients.add(ws)
    try:
        snap = await asyncio.to_thread(hub.snapshot, hub.active_symbol)
        await ws.send_text(json.dumps(snap, ensure_ascii=False))
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            action = msg.get("action")
            if action == "switch":
                sym = str(msg.get("symbol") or "")
                if sym.isdigit() and len(sym) == 6:
                    await hub.switch(sym, ws)
            elif action == "ping":
                await ws.send_text(json.dumps({"type": "pong", "time": msg.get("t")}))
            elif action == "refresh":
                hub.refresh(hub.active_symbol)
                snap = await asyncio.to_thread(hub.snapshot, hub.active_symbol)
                await ws.send_text(json.dumps(snap, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.clients.discard(ws)


@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
