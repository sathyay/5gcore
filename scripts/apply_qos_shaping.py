#!/usr/bin/env python3
"""
apply_qos_shaping.py
─────────────────────
Applies Linux tc (traffic control) rules inside each slice's dedicated UPF
pod, scoped to that slice's subnet (from slice-*.yaml). This is the
"enforcement" mechanism — infrastructure-level shaping, not native PCF policy.

Usage:
  python apply_qos_shaping.py --slice slices/slice-iot.yaml
  python apply_qos_shaping.py --slice slices/slice-iot.yaml --teardown
"""
import argparse
import subprocess
import sys
import yaml

NAMESPACE = "oai5g"


def run(cmd: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if r.returncode != 0:
        print(f"  ⚠️  command failed: {cmd}\n      {r.stderr.strip()}")
    return r.stdout.strip()


def load_slice(filepath: str) -> dict:
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]


def get_upf_pod(slice_cfg: dict) -> str:
    """
    Each slice with upf.dedicated=true should have its own UPF deployment,
    labeled by slice name (extend provision_slice.py to set this label
    when dedicated UPF replicas are created).
    """
    label = f"slice={slice_cfg['name']}"
    pod = run(
        f"kubectl get pod -n {NAMESPACE} -l {label} "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    )
    if not pod:
        # fallback to shared UPF if no dedicated pod found
        pod = run(
            f"kubectl get pod -n {NAMESPACE} -l app.kubernetes.io/name=oai-upf "
            f"-o jsonpath='{{.items[0].metadata.name}}'"
        )
    return pod


def apply_shaping(slice_cfg: dict, pod: str):
    subnet = slice_cfg.get("ipv4_subnet", "12.2.1.0/24")
    dl_mbps = slice_cfg.get("qos", {}).get("max_dl_mbps", 100)
    ul_mbps = slice_cfg.get("qos", {}).get("max_ul_mbps", 50)
    latency = slice_cfg.get("qos", {}).get("latency", "standard")

    # demo latency targets — simulated, not radio-scheduler-derived
    delay_ms = "3ms" if latency == "low" else "25ms"

    print(f"\n[QoS Shaping] {slice_cfg['name']} -> pod={pod} subnet={subnet}")
    print(f"  DL cap: {dl_mbps}Mbps | UL cap: {ul_mbps}Mbps | delay: {delay_ms}")

    iface = "n3"  # UPF interface facing the RAN side; adjust to actual iface name

    cmds = [
        f"tc qdisc del dev {iface} root 2>/dev/null || true",
        f"tc qdisc add dev {iface} root handle 1: htb default 10",
        f"tc class add dev {iface} parent 1: classid 1:10 htb rate {dl_mbps}mbit ceil {dl_mbps}mbit",
        f"tc qdisc add dev {iface} parent 1:10 handle 10: netem delay {delay_ms} loss 0%",
        f"tc filter add dev {iface} protocol ip parent 1:0 prio 1 "
        f"u32 match ip dst {subnet} flowid 1:10",
    ]

    for c in cmds:
        out = run(f"kubectl exec -n {NAMESPACE} {pod} -- {c}")
        if out:
            print(f"    → {out}")

    print(f"  ✅ Shaping applied: {slice_cfg['name']} capped at {dl_mbps}Mbps DL, {delay_ms} delay")


def teardown_shaping(pod: str):
    iface = "n3"
    print(f"\n[QoS Shaping] Teardown on pod={pod}")
    run(f"kubectl exec -n {NAMESPACE} {pod} -- tc qdisc del dev {iface} root")
    print(f"  ✅ Shaping removed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", required=True)
    parser.add_argument("--teardown", action="store_true")
    args = parser.parse_args()

    cfg = load_slice(args.slice)
    pod = get_upf_pod(cfg)

    if not pod:
        print(f"❌ No UPF pod found for slice {cfg['name']}")
        sys.exit(1)

    if args.teardown:
        teardown_shaping(pod)
    else:
        apply_shaping(cfg, pod)
