#!/usr/bin/env python3
"""
stress_test_isolation.py
──────────────────────────
Orchestrates the full QoS enforcement + isolation proof.
Calls apply_qos_shaping.py and generate_congestion.py as subprocesses
so all scripts stay flat inside scripts/ with no cross-imports needed.

  Step 1: Baseline already done by workflow (verify_slice.py called first)
  Step 2: Shaping already applied by workflow (apply_qos_shaping.py called first)
  Step 3+4: Generate congestion (called here)
  Step 5: Verify isolation — compare measured results against pass criteria
  Step 6: Check HPA autoscale fired
  Step 7: Write isolation_report.json
  Step 8: Teardown shaping

Exit 0 = isolation proven
Exit 1 = isolation violated or measurement failed
"""
import subprocess
import sys
import json
import datetime
import yaml

NAMESPACE  = "oai5g"
REPORT     = "isolation_report.json"

SLICE_FILES = {
    "iot-factory": "slices/slice-iot.yaml",
    "enterprise":  "slices/slice-enterprise.yaml",
}

# ── Pass criteria ─────────────────────────────────────────────
ENTERPRISE_MIN_THROUGHPUT_PCT   = 0.90   # Enterprise must retain ≥90% expected throughput
ENTERPRISE_MAX_LOSS_PCT         = 1.0    # Enterprise must stay under 1% packet loss
IOT_MAX_CAP_OVERSHOOT_PCT       = 1.15   # IoT must not exceed its AMBR by more than 15%

def run(cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, shell=True).stdout.strip()

def load_slice(filepath: str) -> dict:
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]

# ── Step 3+4: Run generate_congestion.py as subprocess ───────
def run_congestion(duration: int) -> dict:
    print(f"\nSTEP 3+4 — Generate congestion ({duration}s)")
    result = subprocess.run(
        [sys.executable, "scripts/generate_congestion.py", "--duration", str(duration)],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"  ⚠️  generate_congestion.py stderr: {result.stderr}")

    # generate_congestion.py writes congestion_results.json
    try:
        with open("congestion_results.json") as f:
            return json.load(f)
    except FileNotFoundError:
        print("  ❌ congestion_results.json not found — congestion script failed")
        return {}

# ── Step 5: Verify isolation ──────────────────────────────────
def verify_isolation(results: dict) -> dict:
    print("\nSTEP 5 — Verify slice isolation")

    iot = results.get("iot-factory", {})
    ent = results.get("enterprise", {})

    iot_cfg = load_slice(SLICE_FILES["iot-factory"])
    iot_cap = iot_cfg["qos"]["max_dl_mbps"]

    # Enterprise expected = what it was asked to send (200Mbps per generate_congestion.py)
    ent_expected = 200

    iot_capped = (
        "throughput_mbps" in iot and
        iot["throughput_mbps"] <= iot_cap * IOT_MAX_CAP_OVERSHOOT_PCT
    )
    ent_unaffected = (
        "throughput_mbps" in ent and
        ent["throughput_mbps"] >= ent_expected * ENTERPRISE_MIN_THROUGHPUT_PCT and
        (ent.get("loss_pct") or 0) <= ENTERPRISE_MAX_LOSS_PCT
    )

    print(f"  {'✅' if iot_capped else '❌'} IoT capped near {iot_cap}Mbps "
          f"(observed: {iot.get('throughput_mbps', 'N/A')}Mbps)")
    print(f"  {'✅' if ent_unaffected else '❌'} Enterprise unaffected "
          f"(throughput: {ent.get('throughput_mbps', 'N/A')}Mbps  "
          f"loss: {ent.get('loss_pct', 'N/A')}%)")

    return {
        "iot_capped_as_configured": iot_capped,
        "enterprise_unaffected":    ent_unaffected,
    }

# ── Step 6: Check HPA autoscale ──────────────────────────────
def check_hpa() -> dict:
    print("\nSTEP 6 — Check UPF autoscale")
    out = run(
        f"kubectl get hpa oai-upf-hpa -n {NAMESPACE} "
        f"-o jsonpath='{{.status.currentReplicas}} {{.status.desiredReplicas}}'"
    )
    parts = out.split()
    current = parts[0] if len(parts) > 0 else "?"
    desired = parts[1] if len(parts) > 1 else "?"
    scaled  = current.isdigit() and desired.isdigit() and int(desired) > int(current)
    print(f"  {'✅' if scaled else 'ℹ️ '} HPA: current={current} desired={desired} "
          f"{'— scaled up ✅' if scaled else '— no scale event'}")
    return {"current_replicas": current, "desired_replicas": desired, "scaled": scaled}

# ── Step 8: Teardown shaping ──────────────────────────────────
def teardown():
    print("\nSTEP 8 — Teardown QoS shaping")
    for name, path in SLICE_FILES.items():
        result = subprocess.run(
            [sys.executable, "scripts/apply_qos_shaping.py",
             "--slice", path, "--teardown"],
            capture_output=True, text=True
        )
        print(result.stdout)

# ── Main ──────────────────────────────────────────────────────
def main():
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*60}")
    print(f"  Multi-Slice QoS Isolation Stress Test")
    print(f"  {now}")
    print(f"{'='*60}")

    results   = run_congestion(duration=60)
    isolation = verify_isolation(results)
    hpa       = check_hpa()

    report = {
        "timestamp": now,
        "results":   results,
        "isolation": isolation,
        "autoscale": hpa,
    }
    with open(REPORT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  📄 Report: {REPORT}")

    teardown()

    passed = all(isolation.values())
    print(f"\n{'='*60}")
    if passed:
        print("  ✅ ISOLATION PROVEN — Enterprise slice protected under IoT overload")
    else:
        print("  ❌ ISOLATION VIOLATED — check shaping rules and UPF separation")
    print(f"{'='*60}\n")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()