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
def check_pods_running() -> bool:
    out = run(
        f"kubectl get pods -n {NAMESPACE} "
        f"-l 'app in (oai-amf,oai-smf,oai-gnb)' "
        f"--field-selector=status.phase=Running --no-headers"
    )
    count = len([l for l in out.strip().splitlines() if l.strip()])
    ok = count >= 3
    print(f"  {'✅' if ok else '❌'} NF pods running: {count}/3 (AMF, SMF, gNB)")
    return ok

# ── Check 2: SCTP association is active ──────────────────────
def check_sctp() -> bool:
    gnb_pod = run(
        f"kubectl get pod -n {NAMESPACE} -l app=oai-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    ).strip()
    assocs = run(
        f"kubectl exec -n {NAMESPACE} {gnb_pod} -c gnb -- "
        f"cat /proc/net/sctp/assocs"
    )
    lines = [l for l in assocs.strip().splitlines() if l.strip()]
    ok = len(lines) > 1
    print(f"  {'✅' if ok else '❌'} SCTP association: {'UP' if ok else 'DOWN'}")
    return ok

# ── Check 3: AMF has registered the slice ────────────────────
def check_amf_slice(slice: dict) -> bool:
    amf_pod = run(
        f"kubectl get pod -n {NAMESPACE} -l app.kubernetes.io/name=oai-amf "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    ).strip()
    logs = run(f"kubectl logs -n {NAMESPACE} {amf_pod} | grep -i 'sst'")
    ok = str(slice["sst"]) in logs
    print(f"  {'✅' if ok else '❌'} AMF slice SST={slice['sst']} registered: {'YES' if ok else 'NO'}")
    return ok

# ── Check 4: gNB broadcasting new NSSAI ──────────────────────
def check_gnb_nssai(slice: dict) -> bool:
    gnb_pod = run(
        f"kubectl get pod -n {NAMESPACE} -l app=oai-gnb "
        f"-o jsonpath='{{.items[0].metadata.name}}'"
    ).strip()
    logs = run(f"kubectl logs -n {NAMESPACE} {gnb_pod} -c gnb | grep -i 'nssai\\|sst'")
    ok = str(slice["sst"]) in logs
    print(f"  {'✅' if ok else '❌'} gNB NSSAI SST={slice['sst']} broadcasting: {'YES' if ok else 'NO'}")
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
        "pods_running":  check_pods_running(),
        "sctp_up":       check_sctp(),
        "amf_slice":     check_amf_slice(slice_cfg),
        "gnb_nssai":     check_gnb_nssai(slice_cfg),
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
