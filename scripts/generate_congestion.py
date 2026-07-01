#!/usr/bin/env python3
"""
generate_congestion.py
───────────────────────
Drives concurrent iperf3 load from each slice's UE pod through its UPF,
deliberately overdriving the IoT slice past its configured AMBR cap while
the Enterprise slice runs a normal/light load — the contention needed to
prove isolation.

Requires: a second RFsim UE attached on the IoT slice's NSSAI (see
manifests/ue-iot-rfsim.yaml). Without two concurrent UEs there is nothing
to contend over, and "isolation under stress" can't be demonstrated.

Usage:
  python generate_congestion.py --duration 60
"""
import argparse
import subprocess
import threading
import json
import datetime

NAMESPACE = "oai5g"

UE_TARGETS = {
    "iot-factory": {
        "ue_pod_label": "app=oai-nr-ue-iot",
        "server": "iperf-server-iot.oai5g.svc.cluster.local",
        "overdrive_mbps": 300,   # deliberately > slice-iot.yaml cap of 100Mbps
    },
    "enterprise": {
        "ue_pod_label": "app=oai-nr-ue-enterprise",
        "server": "iperf-server-enterprise.oai5g.svc.cluster.local",
        "overdrive_mbps": 200,   # well under slice-enterprise.yaml cap of 1000Mbps
    },
}


def run(cmd: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    return r.stdout.strip()


def get_pod(label: str) -> str:
    return run(
        f"kubectl get pod -n {NAMESPACE} -l {label} "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    )


def run_iperf(slice_name: str, target: dict, duration: int, results: dict):
    pod = get_pod(target["ue_pod_label"])
    if not pod:
        results[slice_name] = {"error": f"UE pod not found for label {target['ue_pod_label']}"}
        return

    cmd = (
        f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"iperf3 -c {target['server']} -t {duration} "
        f"-b {target['overdrive_mbps']}M -J"
    )
    out = run(cmd)
    try:
        data = json.loads(out)
        end = data.get("end", {})
        results[slice_name] = {
            "throughput_mbps": round(
                end.get("sum_received", {}).get("bits_per_second", 0) / 1e6, 1
            ),
            "loss_pct": end.get("sum", {}).get("lost_percent", None),
            "retransmits": end.get("sum_sent", {}).get("retransmits", None),
        }
    except json.JSONDecodeError:
        results[slice_name] = {"error": "iperf3 output not parseable", "raw": out[:500]}


def main(duration: int):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*55}")
    print(f"  Congestion Generation — {now}")
    print(f"  Duration: {duration}s | Slices: {list(UE_TARGETS)}")
    print(f"{'='*55}\n")

    results = {}
    threads = []
    for slice_name, target in UE_TARGETS.items():
        print(f"  ▶ Starting iperf3 on '{slice_name}' "
              f"(target {target['overdrive_mbps']}Mbps)")
        t = threading.Thread(target=run_iperf, args=(slice_name, target, duration, results))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print(f"\n  Results:\n")
    for slice_name, r in results.items():
        if "error" in r:
            print(f"  ❌ {slice_name}: {r['error']}")
        else:
            print(f"  {slice_name:15s} throughput={r['throughput_mbps']}Mbps "
                  f"loss={r['loss_pct']}% retransmits={r['retransmits']}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=60)
    args = parser.parse_args()
    main(args.duration)


# ── Write results to file so stress_test_isolation.py can read them ──
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=60)
    args = parser.parse_args()
    results = main(args.duration)
    with open("congestion_results.json", "w") as f:
        import json as _json
        _json.dump(results, f, indent=2)
    print(f"\n  📄 Results written: congestion_results.json")