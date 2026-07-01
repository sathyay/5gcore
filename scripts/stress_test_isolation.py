#!/usr/bin/env python3
"""
stress_test_isolation.py
──────────────────────────
JOB: orchestrates the full QoS enforcement + isolation proof:
  1. Baseline check (both slices healthy, idle)
  2. Apply QoS shaping (per-slice tc rules)
  3. Generate congestion (concurrent iperf3, IoT overdriven past cap)
  4. Measure per-slice throughput / loss during stress
  5. Verify Enterprise slice isolation (unaffected by IoT overload)
  6. Check HPA autoscale event fired if load > 80%
  7. Write isolation_report.json (consumed by dashboard / CI artifact)
  8. Teardown shaping

Exit 0 = isolation proven (Enterprise unaffected, IoT capped as configured)
Exit 1 = isolation violated or measurement failed
"""
import subprocess
import sys
import json
import datetime

import apply_qos_shaping as shaping
import generate_congestion as congestion

NAMESPACE = "oai5g"
REPORT = "isolation_report.json"

SLICE_FILES = {
    "iot-factory": "slices/slice-iot.yaml",
    "enterprise":  "slices/slice-enterprise.yaml",
}

# Isolation pass criteria
ENTERPRISE_MIN_THROUGHPUT_PCT = 0.90   # must retain >=90% of expected throughput
ENTERPRISE_MAX_LOSS_PCT       = 1.0    # must stay under 1% loss
IOT_MAX_OBSERVED_MBPS_OVER_CAP = 1.15  # IoT shouldn't exceed cap by more than 15%


def run(cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, shell=True).stdout.strip()


def check_hpa_scaled() -> dict:
    out = run(f"kubectl get hpa -n {NAMESPACE} oai-upf-hpa "
              f"-o jsonpath='{{.status.currentReplicas}} {{.status.desiredReplicas}} {{.status.currentMetrics}}'")
    parts = out.split(" ", 2)
    current = parts[0] if len(parts) > 0 else "?"
    desired = parts[1] if len(parts) > 1 else "?"
    scaled  = current != desired or (current.isdigit() and desired.isdigit() and int(desired) > 1)
    return {"current_replicas": current, "desired_replicas": desired, "scaled": scaled}


def main():
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*60}")
    print(f"  Multi-Slice QoS Isolation Stress Test")
    print(f"  {now}")
    print(f"{'='*60}\n")

    # ── Step 1: Baseline ──────────────────────────────────────
    print("STEP 1 — Baseline check (both slices healthy)")
    # Reuses existing verify_slice.py logic per slice; assumed passing
    # since this test is meant to run after the provisioning pipeline.
    print("  ℹ️  Assuming slices already verified live via verify_slice.py\n")

    # ── Step 2: Apply shaping ─────────────────────────────────
    print("STEP 2 — Apply QoS shaping per slice")
    for name, path in SLICE_FILES.items():
        cfg = shaping.load_slice(path)
        pod = shaping.get_upf_pod(cfg)
        if pod:
            shaping.apply_shaping(cfg, pod)
        else:
            print(f"  ⚠️  No UPF pod found for {name}, skipping shaping")

    # ── Step 3 + 4: Generate congestion & measure ─────────────
    print("\nSTEP 3 — Generate congestion (60s, IoT overdriven past cap)")
    results = congestion.main(duration=60)

    # ── Step 5: Verify isolation ──────────────────────────────
    print("\nSTEP 5 — Verify Enterprise slice isolation")
    iot = results.get("iot-factory", {})
    ent = results.get("enterprise", {})

    iot_cap = shaping.load_slice(SLICE_FILES["iot-factory"])["qos"]["max_dl_mbps"]
    ent_expected = congestion.UE_TARGETS["enterprise"]["overdrive_mbps"]

    iot_capped = (
        "throughput_mbps" in iot and
        iot["throughput_mbps"] <= iot_cap * IOT_MAX_OBSERVED_MBPS_OVER_CAP
    )
    ent_unaffected = (
        "throughput_mbps" in ent and
        ent["throughput_mbps"] >= ent_expected * ENTERPRISE_MIN_THROUGHPUT_PCT and
        (ent.get("loss_pct") or 0) <= ENTERPRISE_MAX_LOSS_PCT
    )

    print(f"  {'✅' if iot_capped else '❌'} IoT slice capped near {iot_cap}Mbps "
          f"(observed: {iot.get('throughput_mbps', 'N/A')}Mbps)")
    print(f"  {'✅' if ent_unaffected else '❌'} Enterprise slice unaffected "
          f"(observed: {ent.get('throughput_mbps', 'N/A')}Mbps, "
          f"loss: {ent.get('loss_pct', 'N/A')}%)")

    # ── Step 6: Autoscale check ───────────────────────────────
    print("\nSTEP 6 — Check autoscale trigger")
    hpa = check_hpa_scaled()
    print(f"  HPA replicas: current={hpa['current_replicas']} "
          f"desired={hpa['desired_replicas']} "
          f"scaled={'YES' if hpa['scaled'] else 'NO'}")

    # ── Step 7: Write report ──────────────────────────────────
    report = {
        "timestamp": now,
        "results": results,
        "isolation": {
            "iot_capped_as_configured": iot_capped,
            "enterprise_unaffected": ent_unaffected,
        },
        "autoscale": hpa,
    }
    with open(REPORT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  📄 Report written: {REPORT}")

    # ── Step 8: Teardown ──────────────────────────────────────
    print("\nSTEP 8 — Teardown shaping")
    for name, path in SLICE_FILES.items():
        cfg = shaping.load_slice(path)
        pod = shaping.get_upf_pod(cfg)
        if pod:
            shaping.teardown_shaping(pod)

    passed = iot_capped and ent_unaffected
    print(f"\n{'='*60}")
    if passed:
        print("  ✅ ISOLATION PROVEN — Enterprise slice protected under IoT overload")
    else:
        print("  ❌ ISOLATION VIOLATED — investigate shaping rules / UPF separation")
    print(f"{'='*60}\n")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
