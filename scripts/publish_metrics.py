#!/usr/bin/env python3
"""
publish_metrics.py
────────────────────
Reads isolation_report.json (written by stress_test_isolation.py) and
pushes the key metrics to a Prometheus Pushgateway so Grafana can render
them. Simpler than building a custom UPF exporter — sufficient for a
per-run "live dashboard updates after each stress test" demo.

Usage:
  python publish_metrics.py --report isolation_report.json --gateway http://pushgateway.monitoring:9091
"""
import argparse
import json
import requests

JOB_NAME = "qos_isolation_stress_test"


def publish(report_path: str, gateway_url: str):
    with open(report_path) as f:
        report = json.load(f)

    lines = []
    for slice_name, r in report.get("results", {}).items():
        if "throughput_mbps" in r:
            lines.append(
                f'slice_throughput_mbps{{slice="{slice_name}"}} {r["throughput_mbps"]}'
            )
        if r.get("loss_pct") is not None:
            lines.append(
                f'slice_packet_loss_pct{{slice="{slice_name}"}} {r["loss_pct"]}'
            )

    iso = report.get("isolation", {})
    lines.append(f'isolation_iot_capped {1 if iso.get("iot_capped_as_configured") else 0}')
    lines.append(f'isolation_enterprise_unaffected {1 if iso.get("enterprise_unaffected") else 0}')

    hpa = report.get("autoscale", {})
    lines.append(f'upf_autoscaled {1 if hpa.get("scaled") else 0}')

    payload = "\n".join(lines) + "\n"

    url = f"{gateway_url}/metrics/job/{JOB_NAME}"
    resp = requests.post(url, data=payload)

    print(f"  Pushgateway response: {resp.status_code}")
    print(f"  Metrics pushed:\n{payload}")

    return resp.status_code == 200


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="isolation_report.json")
    parser.add_argument("--gateway", required=True)
    args = parser.parse_args()
    ok = publish(args.report, args.gateway)
    exit(0 if ok else 1)