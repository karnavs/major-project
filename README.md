# Adaptive Congestion Detection & Dynamic Rerouting in SDN

[![Python](https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11-blue.svg)](https://www.python.org/)
[![OpenFlow](https://img.shields.io/badge/OpenFlow-1.3-orange.svg)](https://opennetworking.org/)
[![Ryu SDN](https://img.shields.io/badge/SDN-Ryu%20Controller-green.svg)](https://ryu-sdn.org/)
[![FastAPI](https://img.shields.io/badge/Frontend-FastAPI%20%2B%20WebSocket-teal.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/Tests-58%2F58%20Passing-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

An enterprise-grade, congestion-aware traffic engineering system for Software-Defined Networks (SDN). Combines an **adaptive-threshold congestion detector** (EWMA smoothing + persistence window + dual-threshold hysteresis) with a **dynamic Dijkstra rerouting engine** and an interactive **Real-Time Flow Studio UI**.

---

## 🚀 Key Innovations & Architecture

```
                          [ Sender Hosts ]
                           h1 (10.0.0.1)
                           h2 (10.0.0.2)
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │      s1 (Ingress)     │
                     └───────────┬───────────┘
                                 │
                  ┌──────────────┴──────────────┐
     Normal Flow  │                             │ Congestion Surge
   (Direct Link)  │ [Primary: 10M Capacity]     │ (Dynamic Bypass)
                  ▼                             ▼
     ┌───────────────────────┐     ┌───────────────────────┐
     │      s2 (Egress)      │◄────│      s3 (Bypass)      │
     └───────────┬───────────┘     └───────────────────────┘
                 │
                 ▼
          [ Target Hosts ]
           h3 (10.0.0.3)
           h4 (10.0.0.4)
```

1. **EWMA Utilization Smoothing:** Mitigates micro-burst false positives using an exponential moving average ($\alpha = 0.3$).
2. **Dual-Threshold Hysteresis:**
   - **Enter Congestion ($T_{\text{enter}} = 85\%$):** Requires $N = 3$ consecutive samples above threshold before state transition.
   - **Exit Congestion ($T_{\text{exit}} = 75\%$):** Requires $M = 5$ consecutive samples below threshold before restoring primary route.
3. **Dynamic Dijkstra Route Penalty:** Congested links incur a $10\times$ weight penalty, dynamically shifting flows to underutilized bypass paths ($s1 \to s3 \to s2$).
4. **Flap Prevention & Zero Packet Loss:** Mathematically eliminates route flapping, preserving 100% throughput under heavy 95% traffic surges.

---

## 🖥️ Interactive SDN Flow Studio (Web UI)

The Flow Studio provides a real-time, presentation-grade command center for visualizing network telemetry:

* **Vector Packet Streaming:** Native SVG vector particles mathematically locked onto network paths with zero coordinate drift.
* **Architecture Comparison:** Toggle live between **Standard Static SDN** (showing bufferbloat queuing delay and critical packet drops) and **Our Adaptive SDN** (demonstrating instant lossless bypass).
* **Mission Control Workstation:**
  * Interactive Start/Stop turbine engine controller with GSAP physics.
  * Instant traffic surge injector (`95% Surge` and `10% Relieve`).
  * Precision offered load slider and slow-motion playback presets (`0.25x`, `0.5x`, `1.0x`, `2.0x`).
* **Real-time Telemetry:** Sparkline charts tracking EWMA utilization against $T_{\text{enter}}$ and $T_{\text{exit}}$ boundaries.

---

## ☁️ Deployment Guide (Ready to Deploy)

This repository is structured for one-click deployment to cloud platforms.

### Option 1: Render (Recommended)
This repository includes a `render.yaml` configuration:
1. Connect your GitHub repository to [Render](https://render.com).
2. Choose **New Blueprint Instance** and select this repo.
3. Render automatically detects `render.yaml` and starts the Flow Studio.

### Option 2: Railway / Fly.io / Heroku
The included `Procfile` specifies the web start command:
```bash
web: uvicorn server:app --host 0.0.0.0 --port $PORT
```
Set the environment variable `PORT=8000` (assigned automatically by most PaaS providers).

### Option 3: Docker Container
Build and launch the self-contained container:
```bash
# Build Docker image
docker build -t sdn-flow-studio .

# Run on port 8000
docker run -d -p 8000:8000 --name sdn-studio sdn-flow-studio
```
Access at `http://localhost:8000`.

---

## 💻 Local Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch Flow Studio Web UI
```bash
# Direct runner
python server.py

# Or via Uvicorn
uvicorn server:app --host 127.0.0.1 --port 8000
```
Open your browser at **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.

### 3. Run Automated Terminal Verifications
```bash
# Run all 58 unit & integration tests
python MP_Exe/main.py --test

# Run 13 synthetic detector trace scenarios
python MP_Exe/main.py --synthetic

# Run 70-second timeline simulation
python MP_Exe/main.py --simulate
```

---

## 🔬 Mininet & Ryu OpenFlow 1.3 Deployment (Linux / WSL)

To execute with a hardware-emulated OpenFlow network:

```bash
# Terminal 1: Start Ryu Controller
SDN_CONGESTION_CONFIG=MP_Exe/config/congestion_detector.json ryu-manager MP_Exe/congestion_detection/routing_controller.py

# Terminal 2: Launch Mininet Diamond Topology
sudo python3 MP_Exe/mininet/multipath_topo.py

# Terminal 3: Run automated multi-phase traffic surge scenario
sudo python3 MP_Exe/mininet/reroute_scenario.py
```

---

## 📂 Repository Structure

```
├── Dockerfile                  # Container definition for cloud deployment
├── Procfile                    # PaaS process file (Railway, Heroku)
├── render.yaml                 # Render Blueprint specification
├── requirements.txt            # Python dependencies
├── server.py                   # Production root web server launcher
├── README.md                   # Project documentation
│
├── MP_Exe/                     # Executable SDN Codebase
│   ├── main.py                 # Unified CLI runner
│   ├── server.py               # FastAPI telemetry server
│   ├── static/                 # Flow Studio Web UI (HTML, CSS, SVG)
│   ├── congestion_detection/   # Core algorithms (Detector, Dijkstra, Adapter)
│   ├── mininet/                # Mininet topologies and scenario drivers
│   ├── config/                 # Detector parameters and link capacity configs
│   ├── tests/                  # 58 comprehensive test suites
│   └── docs/                   # Detailed algorithm specifications and test reports
│
├── MP- Final Report/           # Capstone documentation, thesis format, dairy forms
├── Final_Research_Paper.pdf    # Complete research paper
├── Phase I Review.pptx         # Phase 1 presentation deck
└── MP_0_Review.pptx            # Project review deck
```

---

## 📜 License
This project is licensed under the MIT License - see the [LICENSE](MP_Exe/LICENSE) file for details.
