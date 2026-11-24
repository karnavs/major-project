"""FastAPI Production Server for SDN Adaptive Congestion Rerouting Dashboard.

Serves:
- Real-time WebSocket connection for 60fps / 1-second telemetry broadcast
- REST API for step-by-step and sandbox control
- High-performance unslop dashboard frontend
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from congestion_detection.simulation_engine import SDNSimulationEngine

app = FastAPI(
    title="SDN Adaptive Congestion Rerouting Telemetry",
    description="Real-time Network Operations Console for Adaptive SDN Traffic Engineering",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared simulation engine instance
engine = SDNSimulationEngine()
connected_websockets: List[WebSocket] = []
playback_task: asyncio.Task | None = None


class LoadRequest(BaseModel):
    util: float = 0.50


class SpeedRequest(BaseModel):
    speed: float = 1.0


class ModeRequest(BaseModel):
    mode: str = "sandbox"  # 'sandbox' or 'scenario_70s'


async def broadcast_state():
    """Broadcast state to all connected WebSocket clients."""
    if not connected_websockets:
        return
    state = engine.get_state()
    disconnected = []
    for ws in connected_websockets:
        try:
            await ws.send_json(state)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in connected_websockets:
            connected_websockets.remove(ws)


async def _playback_loop():
    """Background task for auto-running simulation ticks."""
    try:
        while engine.is_running:
            delay = 1.0 / max(0.2, min(5.0, engine.speed))
            await asyncio.sleep(delay)
            if not engine.is_running:
                break
            engine.step()
            await broadcast_state()
    except asyncio.CancelledError:
        pass


@app.on_event("startup")
async def startup_event():
    # Ensure static directory exists
    static_dir = os.path.join(BASE_DIR, "static")
    os.makedirs(static_dir, exist_ok=True)


@app.get("/api/state")
def get_state():
    return engine.get_state()


@app.post("/api/step")
async def api_step():
    res = engine.step()
    await broadcast_state()
    return res


@app.post("/api/reset")
async def api_reset():
    global playback_task
    engine.is_running = False
    if playback_task and not playback_task.done():
        playback_task.cancel()
    engine.reset()
    await broadcast_state()
    return engine.get_state()


@app.post("/api/play")
async def api_play(req: SpeedRequest = SpeedRequest()):
    global playback_task
    engine.speed = req.speed
    if not engine.is_running:
        engine.is_running = True
        if playback_task and not playback_task.done():
            playback_task.cancel()
        playback_task = asyncio.create_task(_playback_loop())
    await broadcast_state()
    return {"status": "playing", "speed": engine.speed}


@app.post("/api/pause")
async def api_pause():
    global playback_task
    engine.is_running = False
    if playback_task and not playback_task.done():
        playback_task.cancel()
    await broadcast_state()
    return {"status": "paused"}


@app.post("/api/inject_congestion")
async def api_inject(req: LoadRequest = LoadRequest(util=0.95)):
    engine.inject_congestion(req.util)
    await broadcast_state()
    return engine.get_state()


@app.post("/api/relieve_congestion")
async def api_relieve(req: LoadRequest = LoadRequest(util=0.10)):
    engine.relieve_congestion(req.util)
    await broadcast_state()
    return engine.get_state()


@app.post("/api/set_load")
async def api_set_load(req: LoadRequest):
    engine.set_load(req.util)
    await broadcast_state()
    return engine.get_state()


@app.post("/api/mode")
async def api_set_mode(req: ModeRequest):
    engine.mode = req.mode
    await broadcast_state()
    return {"mode": engine.mode}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    # Send immediate initial state
    await websocket.send_json(engine.get_state())
    try:
        while True:
            data = await websocket.receive_text()
            # Client can send commands via WS as well
            if data == "step":
                engine.step()
                await broadcast_state()
            elif data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)


# Mount static assets
static_path = os.path.join(BASE_DIR, "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/")
def serve_index():
    index_file = os.path.join(BASE_DIR, "static", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<h1>SDN Adaptive Dashboard UI Initializing...</h1>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
