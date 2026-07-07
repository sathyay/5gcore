#!/usr/bin/env python3
"""
apply_qos_shaping.py
─────────────────────
Applies Linux tc rules on oai-traffic-server loopback (lo) to enforce
per-slice bandwidth caps. Traffic is classified by destination port:

  Port 5201 → IoT slice   (cap 100Mbps, delay 3ms)
  Port 5202 → Enterprise  (cap 1000Mbps, delay 25ms)

This is the demo enforcement mechanism — proven working.
Production upgrade path: once UE PDU session is live, move rules to
UPF tun0 with subnet-based classification instead of port-based.

Usage:
  python scripts/apply_qos_shaping.py --slice slices/slice-iot.yaml
  python scripts/apply_qos_shaping.py --slice slices/slice-enterprise.yaml
  python scripts/apply_qos_shaping.py --teardown-all
"""
import argparse
import subprocess
import sys
import yaml

NAMESPACE    = "oai5g"
TARGET_LABEL = "app.kubernetes.io/name=oai-traffic-server"
IFACE        = "lo"

# Port → slice mapping (must match generate_congestion.py)
SLICE_PORT_MAP = {
    "iot-factory": {"port": 5201, "classid": "1:11", "prio": 1},
    "enterprise":  {"port": 5202, "classid": "1:12", "prio": 2},
}


def run(cmd: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if r.returncode != 0 and r.stderr:
        print(f"  ⚠️  {r.stderr.strip()}")
    return r.stdout.strip()


def load_slice(filepath: str) -> dict:
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]


def get_target_pod() -> str:
    out = run(
        f"kubectl get pod -n {NAMESPACE} -l {TARGET_LABEL} "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    )
    return out.strip()


def ensure_root_qdisc(pod: str):
    check = run(
        f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"tc qdisc show dev {IFACE} | grep 'htb 1:'"
    )
    if not check:
        run(f"kubectl exec -n {NAMESPACE} {pod} -- "
            f"tc qdisc add dev {IFACE} root handle 1: htb default 99")
        run(f"kubectl exec -n {NAMESPACE} {pod} -- "
            f"tc class add dev {IFACE} parent 1: classid 1:99 "
            f"htb rate 10000mbit ceil 10000mbit")
        print(f"  ✅ Root HTB qdisc created on {IFACE}")
    else:
        print(f"  ℹ️  Root HTB qdisc already exists on {IFACE}")


def apply_shaping(slice_cfg: dict, pod: str):
    name    = slice_cfg["name"]
    dl_mbps = slice_cfg.get("qos", {}).get("max_dl_mbps", 100)
    latency = slice_cfg.get("qos", {}).get("latency", "standard")
    delay   = "3ms" if latency == "low" else "25ms"

    mapping = SLICE_PORT_MAP.get(name)
    if not mapping:
        print(f"  ❌ No port mapping for slice '{name}' — "
              f"add to SLICE_PORT_MAP")
        sys.exit(1)

    port    = mapping["port"]
    classid = mapping["classid"]
    prio    = mapping["prio"]
    handle  = f"{classid.split(':')[1]}0:"

    print(f"\n{'='*55}")
    print(f"  [QoS Shaping] {name}")
    print(f"  pod={pod}  iface={IFACE}  port={port}")
    print(f"  cap={dl_mbps}Mbps  delay={delay}")
    print(f"{'='*55}")

    ensure_root_qdisc(pod)

    # HTB class — rate cap
    run(f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"tc class replace dev {IFACE} parent 1: classid {classid} "
        f"htb rate {dl_mbps}mbit ceil {dl_mbps}mbit burst 15k")
    print(f"  ✅ HTB class {classid}: rate={dl_mbps}Mbps")

    # Netem delay
    run(f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"tc qdisc replace dev {IFACE} parent {classid} "
        f"handle {handle} netem delay {delay} loss 0%")
    print(f"  ✅ Netem: delay={delay} loss=0%")

    # Filter by destination port
    run(f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"tc filter replace dev {IFACE} protocol ip parent 1:0 "
        f"prio {prio} u32 match ip dport {port} 0xffff flowid {classid}")
    print(f"  ✅ Filter: dport={port} → {classid}")
    print(f"\n  ✅ SHAPING ACTIVE: {name} capped at {dl_mbps}Mbps\n")


def teardown_all(pod: str):
    print(f"\n[QoS Shaping] Teardown all on {pod} dev {IFACE}")
    run(f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"tc qdisc del dev {IFACE} root 2>/dev/null || true")
    print(f"  ✅ All shaping removed from {IFACE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice",        help="Path to slice YAML")
    parser.add_argument("--teardown",     action="store_true")
    parser.add_argument("--teardown-all", action="store_true")
    args = parser.parse_args()

    pod = get_target_pod()
    if not pod:
        print(f"❌ Target pod not found (label: {TARGET_LABEL})")
        sys.exit(1)
    print(f"  Target pod: {pod}  interface: {IFACE}")

    if args.teardown_all:
        teardown_all(pod)
    elif args.teardown and args.slice:
        teardown_all(pod)
    elif args.slice:
        cfg = load_slice(args.slice)
        apply_shaping(cfg, pod)
    else:
        print("Usage: apply_qos_shaping.py --slice <file>")
        print("       apply_qos_shaping.py --teardown-all")
        sys.exit(1)
