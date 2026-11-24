"""Root launcher for SDN Adaptive Flow Studio.

Allows running or deploying directly from repository root:
    uvicorn server:app --host 0.0.0.0 --port 8000
    python server.py
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXE_DIR = os.path.join(BASE_DIR, "MP_Exe")
if EXE_DIR not in sys.path:
    sys.path.insert(0, EXE_DIR)

from MP_Exe.server import app

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
