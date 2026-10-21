# Report subsection (draft — update numbers once Mininet results exist)

**Adaptive congestion detection.** The controller periodically reads OpenFlow port statistics and converts egress byte
counters of each monitored inter-switch port into link utilization. A lightweight, non-machine-learning detector classifies
each port with a four-state machine (NORMAL, CONGESTION_PENDING, CONGESTED, RECOVERY_PENDING). The entry threshold is
adaptive: an exponentially weighted moving average of recent normal utilization plus *k* times a smoothed absolute
deviation, clamped to fixed bounds. Congestion is confirmed only after *N* consecutive samples above the threshold
(persistence), and recovery only after *M* consecutive samples below a lower exit threshold (hysteresis plus recovery
persistence). Samples that look congested never update the baseline, preventing sustained congestion from raising the
threshold. Invalid, stale or missing samples are treated as neutral evidence and can never confirm congestion or recovery.
The detector emits one event per confirmed transition to the routing module and does not modify forwarding state.
The combination of adaptive threshold, persistence and hysteresis is a standard engineering pattern; we do not claim
novelty beyond its integration and evaluation in our SDN testbed. *Evaluation status:* validated on unit tests and
synthetic traces (13/13 scenarios); Mininet/iperf3 evaluation and routing integration are pending.

# Viva cheat-sheet
* **Why utilization?** Available from standard port stats; needs only a known link capacity. Weakness: no latency/loss view.
* **Why adaptive?** A fixed threshold is wrong across different loads; baseline+k·deviation follows normal behaviour, clamped so it can't go silly.
* **Why not let congested samples update the baseline?** Otherwise sustained congestion becomes the "new normal" and the threshold chases it.
* **Persistence vs hysteresis?** Persistence = *how long* before changing state; hysteresis = *different levels* for entering and leaving. Together they stop flapping.
* **Why recovery slower (M=5 > N=3)?** Premature recovery causes route flapping, which is costlier than a few extra congested seconds. Measured cost: 18 s in the gradual-recovery trace.
* **What if stats are missing?** Neutral: never confirms congestion/recovery; 5 invalid samples drop pending states back to the last confirmed one.
* **Does the detector reroute?** No. It emits `CONGESTION_CONFIRMED`/`RECOVERY_CONFIRMED`; routing owns policy.
* **What is NOT proven?** Real Mininet behaviour, parameter optimality, any throughput/latency/loss benefit.
