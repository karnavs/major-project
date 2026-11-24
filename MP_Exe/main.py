#!/usr/bin/env python3
"""Unified CLI and Runner for SDN Adaptive Congestion-Aware Traffic Rerouting & Load Distribution.

Usage:
    python main.py                 # Interactive menu
    python main.py --simulate      # Run end-to-end discrete event simulation
    python main.py --test          # Run full test suite (57 tests)
    python main.py --synthetic     # Run 13 synthetic detector trace scenarios
    python main.py --info          # Display network topology and active configurations
    python main.py --controller    # Launch the Ryu OpenFlow 1.3 controller
"""
import argparse
import json
import os
import subprocess
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_tests():
    print("\n" + "=" * 65)
    print("  RUNNING UNIT & INTEGRATION TEST SUITE (57 TESTS)")
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
        print("Note: Ryu natively runs in a Linux/WSL environment. On Windows, use the simulation mode:")
        print("      python main.py --simulate")
        return 1


def interactive_menu():
    while True:
        print("\n" + "=" * 65)
        print("  SDN ADAPTIVE CONGESTION & REROUTING SYSTEM")
        print("=" * 65)
        print("1. Run End-to-End Traffic Rerouting Simulation")
        print("2. Run All Unit & Integration Tests (57 tests)")
        print("3. Run 13 Synthetic Detector Traces")
        print("4. View Topology & System Information")
        print("5. Launch Ryu OpenFlow Controller")
        print("6. Exit")

        choice = input("\nEnter choice (1-6): ").strip()
        if choice == "1":
            run_simulation()
        elif choice == "2":
            run_tests()
        elif choice == "3":
            run_synthetic()
        elif choice == "4":
            display_info()
        elif choice == "5":
            run_controller()
        elif choice == "6" or choice.lower() == "q":
            print("Exiting.")
            break
        else:
            print("Invalid selection. Please enter a number 1-6.")


def main():
    parser = argparse.ArgumentParser(description="SDN Congestion Rerouting CLI")
    parser.add_argument("--simulate", action="store_true", help="Run end-to-end discrete event simulation")
    parser.add_argument("--test", action="store_true", help="Run unit & integration test suite")
    parser.add_argument("--synthetic", action="store_true", help="Run synthetic trace scenarios")
    parser.add_argument("--info", action="store_true", help="Display topology and active configurations")
    parser.add_argument("--controller", action="store_true", help="Launch the Ryu OpenFlow 1.3 controller")

    args = parser.parse_args()

    if args.simulate:
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
