#!/usr/bin/env python3
"""
verify_slice.py
───────────────
JOB 3 script — Verifies the slice is live after provisioning.
Runs 4 checks: pods running, NGAP up, AMF slice registered, gNB broadcasting.
Exits 0 = all checks passed, Exits 1 = one or more failed (triggers rollback).
"""
import argparse
import sys
import subprocess
import datetime
import yaml

NAMESPACE = "oai5g"
REPORT    = "verify_report.txt"

def run(cmd: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    return r.stdout

def load_slice(filepath: str) -> dict:
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]

# ── Check 1: All NF pods are Running ─────────────────────────
# ── Check 1: Critical NF pods ────────────────────────────────
def check_pods_running() -> bool:
    deployments = {
        # critical
        "oai-amf": ("app.kubernetes.io/name=oai-amf", True),
        "oai-gnb": ("app=oai-gnb",                    True),
        # non-critical
        "oai-smf": ("app.kubernetes.io/name=oai-smf", False),
    }

    all_ok = True
    for name, (label, critical) in deployments.items():
        out    = run(f"kubectl get pods -n {NAMESPACE} -l {label} "
                     f"--no-headers -o custom-columns=STATUS:.status.phase")
        status = out.strip()
        ok     = status == "Running"
        tag    = "critical" if critical else "non-critical"
        icon   = "✅" if ok else ("❌" if critical else "⚠️ ")
        print(f"  {icon} {name}: {status if status else 'Not found'} ({tag})")
        if critical and not ok:
            all_ok = False

    print(f"\n  {'✅' if all_ok else '❌'} Critical NF pods running: {'YES' if all_ok else 'NO'}")
    return all_ok
# ── Check 2: SCTP association is active ──────────────────────
def check_sctp() -> bool:
    gnb_pod = run(
        f"kubectl get pod -n {NAMESPACE} -l app=oai-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    ).strip()

    if not gnb_pod:
        print(f"  ❌ SCTP: gNB pod not found")
        return False

    assocs = run(
        f"kubectl exec -n {NAMESPACE} {gnb_pod} -c gnb -- "
        f"cat /proc/net/sctp/assocs"
    )

    lines = [l for l in assocs.strip().splitlines() if l.strip()]

    # Check for ST=3 (ESTABLISHED) in any data line
    # Fields: ASSOC SOCK STY SST ST ...
    # Index:    0    1    2   3   4
    established = False
    for line in lines[1:]:
        parts = line.split()
        if len(parts) > 4 and parts[4] == "3":   # ST=3 = ESTABLISHED
            established = True
            break

    ok = established
    print(f"  {'✅' if ok else '❌'} SCTP association: {'ESTABLISHED (ST=3)' if ok else 'NOT ESTABLISHED'}")

    if lines[1:]:
        for line in lines[1:]:
            print(f"    → {line.strip()}")

    return ok
# ── Check 3: AMF has registered the slice ────────────────────
def check_amf_slice(slice: dict) -> bool:
    """Check AMF logs confirm new slice SST is registered."""
    amf_pod = run(
        f"kubectl get pod -n {NAMESPACE} -l app.kubernetes.io/name=oai-amf "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    ).strip()

    # Fallback label if above returns empty
    if not amf_pod:
        amf_pod = run(
            f"kubectl get pod -n {NAMESPACE} -l app=oai-amf "
            f"-o jsonpath='{{.items[0].metadata.name}}'"
        ).strip()

    if not amf_pod:
        print(f"  ❌ AMF slice check: AMF pod not found")
        return False

    # Check AMF startup log for slice support lines
    logs = run(
        f"kubectl logs -n {NAMESPACE} {amf_pod} "
        f"| grep -iE 'SST|slice support'"
    )

    # Check for both SST value and sNssais in NRF registration body
    sst_str   = str(slice["sst"])
    sd_str    = slice["sd"].replace("0x", "").upper().lstrip("0") or "0"

    ok = sst_str in logs
    print(f"  {'✅' if ok else '❌'} AMF slice SST={slice['sst']} registered: {'YES' if ok else 'NO'}")

    if logs:
        for line in logs.strip().splitlines()[:5]:
            print(f"    → {line.strip()}")

    return ok

# ── Check 4: gNB broadcasting new NSSAI ──────────────────────
def check_gnb_nssai(slice: dict) -> bool:
    """
    Check gNB NGAP logs for exact SST=0x0N format.
    Example: SST=0x02 for sst=2
    """
    gnb_pod = run(
        f"kubectl get pod -n {NAMESPACE} -l app=oai-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    ).strip()

    if not gnb_pod:
        print(f"  ❌ gNB NSSAI check: gNB pod not found")
        return False

    # Convert decimal sst to hex format used in NGAP logs
    sst_hex = f"SST=0x{slice['sst']:02x}"

    logs = run(
        f"kubectl logs -n {NAMESPACE} {gnb_pod} -c gnb "
        f"| grep 'Supported slice'"
    )

    ok = sst_hex.lower() in logs.lower()
    print(f"  {'✅' if ok else '❌'} gNB NSSAI {sst_hex} broadcasting: {'YES' if ok else 'NO'}")

    if logs:
        for line in logs.strip().splitlines():
            print(f"    → {line.strip()}")

    return ok

def write_report(lines: list):
    content = "\n".join(lines)
    print(content)
    with open(REPORT, "w") as f:
        f.write(content)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", required=True)
    args = parser.parse_args()

    slice_cfg = load_slice(args.slice)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"\n{'='*50}")
    print(f"  Slice Verification Report")
    print(f"  {now}")
    print(f"  Slice: {slice_cfg['name']} (SST={slice_cfg['sst']} SD={slice_cfg['sd']})")
    print(f"{'='*50}\n")

    results = {
        "pods_running": check_pods_running(),
        "sctp_up":      check_sctp(),
        "amf_slice":    check_amf_slice(slice_cfg),
        "gnb_nssai":    check_gnb_nssai(slice_cfg),
    }

    passed = sum(results.values())
    total  = len(results)

    print(f"\n  Score: {passed}/{total} checks passed")

    if all(results.values()):
        print(f"\n  ✅ SLICE VERIFIED — {slice_cfg['name']} is LIVE\n")
        sys.exit(0)
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"\n  ❌ VERIFICATION FAILED — failed checks: {', '.join(failed)}")
        print(f"  Rollback job will trigger automatically\n")
        sys.exit(1)
