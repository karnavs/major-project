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
import traceback
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
# Enable playback by default so user sees live network ticks immediately
engine.is_running = True

connected_websockets: List[WebSocket] = []
playback_task: asyncio.Task | None = None


class LoadRequest(BaseModel):
    util: float = 0.50
    auto_trigger: bool = True


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
        while True:
            if engine.is_running:
                delay = 1.0 / max(0.2, min(5.0, engine.speed))
                await asyncio.sleep(delay)
                if engine.is_running:
                    try:
                        engine.step()
                        await broadcast_state()
                    except Exception as ex:
                        print("Error during simulation step:", ex)
                        traceback.print_exc()
            else:
                await asyncio.sleep(0.3)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print("Playback task exception:", e)


@app.on_event("startup")
async def startup_event():
    global playback_task
    static_dir = os.path.join(BASE_DIR, "static")
    os.makedirs(static_dir, exist_ok=True)
    if playback_task is None or playback_task.done():
        playback_task = asyncio.create_task(_playback_loop())


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
    engine.reset()
    engine.is_running = True
    await broadcast_state()
    return engine.get_state()


@app.post("/api/play")
async def api_play(req: SpeedRequest = SpeedRequest()):
    engine.speed = req.speed
    engine.is_running = True
    await broadcast_state()
    return {"status": "playing", "speed": engine.speed}


@app.post("/api/pause")
async def api_pause():
    engine.is_running = False
    await broadcast_state()
    return {"status": "paused"}


@app.post("/api/inject_congestion")
async def api_inject(req: LoadRequest = LoadRequest(util=0.95, auto_trigger=True)):
    engine.inject_congestion(req.util, auto_trigger=req.auto_trigger)
    await broadcast_state()
    return engine.get_state()


@app.post("/api/relieve_congestion")
async def api_relieve(req: LoadRequest = LoadRequest(util=0.10, auto_trigger=True)):
    engine.relieve_congestion(req.util, auto_trigger=req.auto_trigger)
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
