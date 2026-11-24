#!/usr/bin/env python3
"""Unified CLI and Runner for SDN Adaptive Congestion-Aware Traffic Rerouting & Load Distribution.

Usage:
    python main.py                 # Interactive menu
    python main.py --ui            # Launch interactive Web UI dashboard (FastAPI + WebSockets)
    python main.py --simulate      # Run end-to-end discrete event simulation
    python main.py --test          # Run full test suite (58 tests)
    python main.py --synthetic     # Run 13 synthetic detector trace scenarios
    python main.py --info          # Display network topology and active configurations
    python main.py --controller    # Launch the Ryu OpenFlow 1.3 controller
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_tests():
    print("\n" + "=" * 65)
    print("  RUNNING UNIT & INTEGRATION TEST SUITE (58 TESTS)")
    print("=" * 65)
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.join(BASE_DIR, "tests"), top_level_dir=BASE_DIR)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def run_synthetic():
    print("\n" + "=" * 65)
    print("  RUNNING 13 SYNTHETIC TRACE SCENARIOS")
    print("=" * 65)
    script = os.path.join(BASE_DIR, "scripts", "run_synthetic_traces.py")
    return subprocess.call([sys.executable, script], cwd=BASE_DIR)


def run_simulation():
    print("\n" + "=" * 65)
    print("  RUNNING END-TO-END TRAFFIC REROUTING & RECOVERY SIMULATION")
    print("=" * 65)
    script = os.path.join(BASE_DIR, "scripts", "simulate_reroute.py")
    return subprocess.call([sys.executable, script], cwd=BASE_DIR)


def run_ui(host="127.0.0.1", port=8000, auto_open=True):
    print("\n" + "=" * 65)
    print("  LAUNCHING SDN ADAPTIVE CONGESTION TELEMETRY DASHBOARD")
    print("=" * 65)
    print(f"[*] Dashboard URL: http://{host}:{port}")
    print("[*] WebSocket Telemetry: ws://{host}:{port}/ws")
    print("[*] Press Ctrl+C in terminal to stop the server.\n")

    def open_browser():
        time.sleep(1.2)
        url = f"http://{host}:{port}"
        print(f"[*] Opening browser: {url}")
        webbrowser.open(url)

    if auto_open:
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        import uvicorn
        from server import app
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0
    except ImportError:
        print("[ERROR] 'uvicorn' or 'fastapi' not installed.")
        print("Install with: pip install fastapi uvicorn")
        return 1
    except KeyboardInterrupt:
        print("\nUI Server stopped.")
        return 0


def display_info():
    print("\n" + "=" * 65)
    print("  PROJECT INFORMATION & TOPOLOGY CONFIGURATION")
    print("=" * 65)
    print("Project: Adaptive Congestion-Aware Traffic Rerouting and Load Distribution in SDN")
    print("Architecture:")
    print("  - Detection: EWMA adaptive threshold + persistence (N=3) + hysteresis (margin=0.10, M=5)")
    print("  - Routing: Dijkstra shortest-path with dynamic congestion penalty weights")
    print("  - Load Distribution: Multi-path least-loaded flow allocation")
    print("  - Controller: Ryu OpenFlow 1.3 with dynamic OFPFlowMod updates")

    cfg_path = os.path.join(BASE_DIR, "config", "congestion_detector.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        print(f"\nConfiguration loaded from: {cfg_path}")
        print(f"  - Polling interval: {cfg.get('poll_interval_s')} s")
        print(f"  - Detector parameters: {cfg.get('detector')}")
        print("  - Monitored port capacities (bps):")
        for k, v in cfg.get("adapter", {}).get("capacity_bps", {}).items():
            print(f"      Switch:Port {k:8s} -> {v / 1e6:.1f} Mbit/s")
    else:
        print("\nActive config file config/congestion_detector.json not found.")

    print("\nDiamond Multipath Topology:")
    print("      [h1, h2] ---> [s1 Ingress]")
    print("                       |       \\")
    print("        Primary (10M)  |        \\ Bypass (10M)")
    print("                       v         v")
    print("                  [s2 Egress] <- [s3 Bypass]")
    print("                       |")
    print("                   [h3, h4]")
    return 0


def run_controller():
    print("\n" + "=" * 65)
    print("  LAUNCHING RYU OPENFLOW 1.3 CONTROLLER")
    print("=" * 65)
    cfg_path = os.path.join(BASE_DIR, "config", "congestion_detector.json")
    os.environ["SDN_CONGESTION_CONFIG"] = cfg_path
    ctrl_path = os.path.join(BASE_DIR, "congestion_detection", "routing_controller.py")
    cmd = ["ryu-manager", ctrl_path]
    print(f"Executing: {' '.join(cmd)}")
    try:
        return subprocess.call(cmd, cwd=BASE_DIR)
    except FileNotFoundError:
        print("\n[ERROR] 'ryu-manager' is not installed in the current environment.")
        print("Note: Ryu natively runs in a Linux/WSL environment. On Windows, use the simulation/UI mode:")
        print("      python main.py --ui")
        print("      python main.py --simulate")
        return 1


def interactive_menu():
    while True:
        print("\n" + "=" * 65)
        print("  SDN ADAPTIVE CONGESTION & REROUTING SYSTEM")
        print("=" * 65)
        print("1. Launch Interactive Web Dashboard UI (Panel Showcase)")
        print("2. Run End-to-End Traffic Rerouting Simulation")
        print("3. Run All Unit & Integration Tests (58 tests)")
        print("4. Run 13 Synthetic Detector Traces")
        print("5. View Topology & System Information")
        print("6. Launch Ryu OpenFlow Controller")
        print("7. Exit")

        choice = input("\nEnter choice (1-7): ").strip()
        if choice == "1":
            run_ui()
        elif choice == "2":
            run_simulation()
        elif choice == "3":
            run_tests()
        elif choice == "4":
            run_synthetic()
        elif choice == "5":
            display_info()
        elif choice == "6":
            run_controller()
        elif choice == "7" or choice.lower() == "q":
            print("Exiting.")
            break
        else:
            print("Invalid selection. Please enter a number 1-7.")


def main():
    parser = argparse.ArgumentParser(description="SDN Congestion Rerouting CLI & Web UI")
    parser.add_argument("--ui", action="store_true", help="Launch interactive Web Dashboard UI")
    parser.add_argument("--port", type=int, default=8000, help="Port for Web Dashboard (default: 8000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host binding (default: 127.0.0.1)")
    parser.add_argument("--no-open", action="store_true", help="Do not automatically open browser on startup")
    parser.add_argument("--simulate", action="store_true", help="Run end-to-end discrete event simulation")
    parser.add_argument("--test", action="store_true", help="Run unit & integration test suite")
    parser.add_argument("--synthetic", action="store_true", help="Run synthetic trace scenarios")
    parser.add_argument("--info", action="store_true", help="Display topology and active configurations")
    parser.add_argument("--controller", action="store_true", help="Launch the Ryu OpenFlow 1.3 controller")

    args = parser.parse_args()

    if args.ui:
        sys.exit(run_ui(host=args.host, port=args.port, auto_open=not args.no_open))
    elif args.simulate:
        sys.exit(run_simulation())
    elif args.test:
        sys.exit(run_tests())
    elif args.synthetic:
        sys.exit(run_synthetic())
    elif args.info:
        sys.exit(display_info())
    elif args.controller:
        sys.exit(run_controller())
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
