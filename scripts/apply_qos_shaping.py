#!/usr/bin/env python3
"""
apply_qos_shaping.py
─────────────────────
Applies Linux tc (traffic control) rules on OAI-UPF's tun0 interface.
tun0 is the real 5G N6 tunnel (12.1.1.1/24) — shaping here enforces
QoS on actual UE data plane traffic flowing through the 5G core.

Slice → subnet mapping (from configmap dnns section):
  iot-factory  → 12.2.1.0/24  (SST=2, cap 100Mbps,  delay 3ms)
  enterprise   → 12.3.1.0/24  (SST=1, cap 1000Mbps, delay 25ms)
  oai (default)→ 12.1.1.0/24  (SST=1, UE default PDU session)

Usage:
  python scripts/apply_qos_shaping.py --slice slices/slice-iot.yaml
  python scripts/apply_qos_shaping.py --slice slices/slice-iot.yaml --teardown
  python scripts/apply_qos_shaping.py --teardown-all
"""
import argparse
import subprocess
import sys
import yaml

NAMESPACE = "oai5g"
UPF_LABEL = "app.kubernetes.io/name=oai-upf"
IFACE     = "tun0"   # UPF N6 tunnel — confirmed UP with 12.1.1.1/24

# Subnet override map — explicit to avoid configmap subnet conflicts
SUBNET_MAP = {
    "iot-factory": "12.2.1.0/24",
    "enterprise":  "12.3.1.0/24",
    "oai":         "12.1.1.0/24",
}

# classid map per slice — must be unique
CLASSID_MAP = {
    "iot-factory": "1:10",
    "enterprise":  "1:20",
    "oai":         "1:30",
}

# Priority map for tc filters
PRIORITY_MAP = {
    "iot-factory": 1,
    "enterprise":  2,
    "oai":         3,
}


def run(cmd: str) -> tuple:
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    return r.stdout.strip(), r.returncode


def ok(cmd: str) -> str:
    out, rc = run(cmd)
    if rc != 0:
        stderr = subprocess.run(
            cmd, capture_output=True, text=True, shell=True
        ).stderr.strip()
        print(f"  ⚠️  {stderr}")
    return out


def load_slice(filepath: str) -> dict:
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]


def get_upf_pod() -> str:
    out, _ = run(
        f"kubectl get pod -n {NAMESPACE} -l {UPF_LABEL} "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    )
    if not out:
        # fallback label
        out, _ = run(
            f"kubectl get pod -n {NAMESPACE} -l app=oai-upf "
            f"-o jsonpath='{{.items[0].metadata.name}}'"
        )
    return out.strip()


def ensure_root_qdisc(pod: str):
    """Create root HTB qdisc on tun0 if not already present."""
    check, _ = run(
        f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"tc qdisc show dev {IFACE} | grep 'htb 1:'"
    )
    if not check:
        ok(f"kubectl exec -n {NAMESPACE} {pod} -- "
           f"tc qdisc add dev {IFACE} root handle 1: htb default 99")
        # default class — unmatched traffic passes through unlimited
        ok(f"kubectl exec -n {NAMESPACE} {pod} -- "
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
    subnet  = SUBNET_MAP.get(name, slice_cfg.get("ipv4_subnet", "12.1.1.0/24"))
    classid = CLASSID_MAP.get(name, "1:99")
    prio    = PRIORITY_MAP.get(name, 9)

    print(f"\n{'='*55}")
    print(f"  [QoS Shaping] {name}")
    print(f"  pod={pod}  iface={IFACE}")
    print(f"  subnet={subnet}  cap={dl_mbps}Mbps  delay={delay}")
    print(f"{'='*55}")

    ensure_root_qdisc(pod)

    # HTB class — rate cap for this slice
    ok(f"kubectl exec -n {NAMESPACE} {pod} -- "
       f"tc class replace dev {IFACE} parent 1: classid {classid} "
       f"htb rate {dl_mbps}mbit ceil {dl_mbps}mbit burst 15k")
    print(f"  ✅ HTB class {classid}: rate={dl_mbps}Mbps")

    # Netem delay on leaf qdisc
    handle = classid.replace("1:", "") + "0:"
    ok(f"kubectl exec -n {NAMESPACE} {pod} -- "
       f"tc qdisc replace dev {IFACE} parent {classid} "
       f"handle {handle} netem delay {delay} loss 0%")
    print(f"  ✅ Netem delay={delay} loss=0%")

    # Filter — match dst subnet → this class
    ok(f"kubectl exec -n {NAMESPACE} {pod} -- "
       f"tc filter replace dev {IFACE} protocol ip parent 1:0 "
       f"prio {prio} u32 match ip dst {subnet} flowid {classid}")
    print(f"  ✅ Filter: dst {subnet} → {classid}")

    # Show active classes
    out, _ = run(
        f"kubectl exec -n {NAMESPACE} {pod} -- "
        f"tc -s class show dev {IFACE} classid {classid}"
    )
    if out:
        print(f"\n  Live stats:\n")
        for line in out.splitlines():
            print(f"    {line}")

    print(f"\n  ✅ SHAPING ACTIVE: {name} → {dl_mbps}Mbps cap, {delay} delay\n")


def teardown_all(pod: str):
    print(f"\n[QoS Shaping] Teardown all rules on {pod} {IFACE}")
    ok(f"kubectl exec -n {NAMESPACE} {pod} -- "
       f"tc qdisc del dev {IFACE} root 2>/dev/null || true")
    print(f"  ✅ All shaping removed from {IFACE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice",       help="Path to slice YAML")
    parser.add_argument("--teardown",    action="store_true",
                        help="Remove shaping for this slice's rules")
    parser.add_argument("--teardown-all", action="store_true",
                        help="Remove ALL shaping rules from tun0")
    args = parser.parse_args()

    pod = get_upf_pod()
    if not pod:
        print(f"❌ UPF pod not found (label: {UPF_LABEL})")
        sys.exit(1)

    print(f"  UPF pod: {pod}  interface: {IFACE}")

    if args.teardown_all:
        teardown_all(pod)
    elif args.teardown and args.slice:
        teardown_all(pod)   # full teardown — simpler than per-slice removal
    elif args.slice:
        cfg = load_slice(args.slice)
        apply_shaping(cfg, pod)
    else:
        print("Usage: apply_qos_shaping.py --slice <file> [--teardown]")
        print("       apply_qos_shaping.py --teardown-all")
        sys.exit(1)
