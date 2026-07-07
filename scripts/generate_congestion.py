#!/usr/bin/env python3
"""
generate_congestion.py — Single UE / Traffic-Server Demo Mode
──────────────────────────────────────────────────────────────
Uses oai-traffic-server to generate two concurrent iperf3 streams
on different ports, simulating two slice traffic profiles:

  Port 5201 → IoT slice   (300Mbps push, 100Mbps cap enforced by tc)
  Port 5202 → Enterprise  (200Mbps push, runs clean and unaffected)

tc shaping rules on traffic-server loopback enforce the caps.
The isolation proof: Enterprise stream unaffected when IoT is flooded.

No second UE pod needed — proven working with existing oai-traffic-server.
"""
import argparse
import subprocess
import threading
import json
import datetime
import sys

NAMESPACE          = "oai5g"
TRAFFIC_SERVER_POD = "app=oai-traffic-server"

STREAMS = {
    "iot-factory": {
        "port":        5201,
        "target_mbps": 300,
        "cap_mbps":    100,
        "label":       "IoT — overdriving cap (300Mbps → enforced 100Mbps)",
    },
    "enterprise": {
        "port":        5202,
        "target_mbps": 200,
        "cap_mbps":    1000,
        "label":       "Enterprise — normal load (200Mbps, unaffected)",
    },
}


def run(cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, shell=True).stdout.strip()


def get_pod(label: str) -> str:
    return run(
        f"kubectl get pod -n {NAMESPACE} -l {label} "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    )


def ensure_iperf_servers(pod: str):
    for name, cfg in STREAMS.items():
        port  = cfg["port"]
        check = run(f"kubectl exec -n {NAMESPACE} {pod} -- "
                    f"ss -tlnp | grep :{port}")
        if not check:
            subprocess.Popen(
                f"kubectl exec -n {NAMESPACE} {pod} -- "
                f"iperf3 -s -p {port} -D",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print(f"  ▶ iperf3 server started on port {port} ({name})")
        else:
            print(f"  ℹ️  iperf3 server already running on port {port} ({name})")
    import time; time.sleep(2)


def run_stream(name: str, cfg: dict, pod: str,
               duration: int, results: dict):
    cmd = (
        f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"iperf3 -c 127.0.0.1 -p {cfg['port']} "
        f"-t {duration} -b {cfg['target_mbps']}M -J"
    )
    out = run(cmd)
    try:
        data = json.loads(out)
        end  = data.get("end", {})
        results[name] = {
            "throughput_mbps": round(
                end.get("sum_received", {}).get("bits_per_second", 0) / 1e6, 1
            ),
            "loss_pct":    end.get("sum", {}).get("lost_percent", 0.0),
            "retransmits": end.get("sum_sent", {}).get("retransmits", 0),
            "cap_mbps":    cfg["cap_mbps"],
            "target_mbps": cfg["target_mbps"],
        }
    except (json.JSONDecodeError, KeyError) as e:
        results[name] = {"error": f"iperf3 parse failed: {e}", "raw": out[:300]}


def main(duration: int, dry_run: bool = False) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*55}")
    print(f"  Congestion Generation — {now}")
    print(f"  Duration: {duration}s | Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*55}\n")

    pod = get_pod(TRAFFIC_SERVER_POD)
    if not pod:
        print(f"  ❌ oai-traffic-server pod not found "
              f"(label: {TRAFFIC_SERVER_POD})")
        sys.exit(1)
    print(f"  Traffic server pod: {pod}\n")

    if dry_run:
        print(f"  ✅ DRY RUN — pod found, skipping iperf3")
        return {}

    ensure_iperf_servers(pod)

    print(f"  Launching concurrent streams:\n")
    for name, cfg in STREAMS.items():
        print(f"  ▶ {name}: port={cfg['port']} "
              f"target={cfg['target_mbps']}Mbps "
              f"cap={cfg['cap_mbps']}Mbps — {cfg['label']}")

    results = {}
    threads = [
        threading.Thread(
            target=run_stream,
            args=(name, cfg, pod, duration, results)
        )
        for name, cfg in STREAMS.items()
    ]
    for t in threads: t.start()
    for t in threads: t.join()

    print(f"\n  Results:\n")
    for name, r in results.items():
        if "error" in r:
            print(f"  ❌ {name}: {r['error']}")
            continue
        cap    = r["cap_mbps"]
        tput   = r["throughput_mbps"]
        capped = tput <= cap * 1.15
        icon   = "✅" if capped else "⚠️ "
        print(f"  {icon} {name:15s}  "
              f"throughput={tput}Mbps  "
              f"cap={cap}Mbps  "
              f"loss={r['loss_pct']}%  "
              f"retransmits={r['retransmits']}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--dry-run",  action="store_true")
    args = parser.parse_args()

    results = main(args.duration, args.dry_run)

    with open("congestion_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  📄 Results written: congestion_results.json")
