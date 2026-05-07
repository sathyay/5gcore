# scripts/check_amf_registration.py
import subprocess, datetime, sys

NAMESPACE = "oai5g"
GNB_LABEL = "app=oai-gnb"
AMF_LABEL = "app=oai-amf"
REPORT    = "amf_report.txt"

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, shell=True)

def get_pod_name(label):
    r = run(f"kubectl get pod -n {NAMESPACE} -l {label} "
            f"-o jsonpath='{{.items[0].metadata.name}}'")
    return r.stdout.strip()

def pod_status(label):
    r = run(f"kubectl get pod -n {NAMESPACE} -l {label} "
            f"-o jsonpath='{{.items[0].status.phase}}'")
    return r.stdout.strip()

def check_sctp_assocs(pod):
    """Live check - reads current SCTP state, not logs"""
    r = run(f"kubectl exec -n {NAMESPACE} {pod} -c gnb -- "
            f"cat /proc/net/sctp/assocs")
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    # More than just the header line = active association
    return len(lines) > 1, r.stdout.strip()

def get_sctp_raddr(pod):
    """Get remote AMF address from live SCTP assoc"""
    r = run(f"kubectl exec -n {NAMESPACE} {pod} -c gnb -- "
            f"cat /proc/net/sctp/assocs")
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 13:
            return parts[-3]   # RADDRS field
    return "unknown"

def check_ngap_in_full_logs(pod):
    """Search full logs for registration line"""
    r = run(f"kubectl logs -n {NAMESPACE} {pod} -c gnb "
            f"| grep 'associated AMF'")
    for line in reversed(r.stdout.splitlines()):
        if "associated AMF" in line:
            try:
                token = line.split("associated AMF")[-1].strip().split()[0]
                return int(token)
            except (IndexError, ValueError):
                continue
    return -1

def write_report(lines):
    content = "\n".join(lines)
    print(content)
    with open(REPORT, "w") as f:
        f.write(content)

# ── Main ─────────────────────────────────────────
now       = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
gnb_pod   = get_pod_name(GNB_LABEL)
amf_pod   = get_pod_name(AMF_LABEL)
gnb_state = pod_status(GNB_LABEL)
amf_state = pod_status(AMF_LABEL)

# Primary check — live SCTP state
sctp_ok, sctp_raw = check_sctp_assocs(gnb_pod)
amf_raddr         = get_sctp_raddr(gnb_pod) if sctp_ok else "none"

# Secondary check — full log grep
amf_count = check_ngap_in_full_logs(gnb_pod)

report = [
    "=" * 50,
    "  OAI 5G AMF Registration Report",
    f"  {now}",
    "=" * 50,
    "",
    f"  gNB Pod      : {gnb_pod}",
    f"  gNB Status   : {gnb_state}",
    f"  AMF Pod      : {amf_pod}",
    f"  AMF Status   : {amf_state}",
    "",
    f"  SCTP Live State  : {'UP' if sctp_ok else 'DOWN'}",
    f"  AMF Remote Addr  : {amf_raddr}",
    f"  NGAP Log Check   : associated AMF {amf_count}",
    "",
]

# Decision based on live SCTP state (primary)
if sctp_ok:
    report += ["  OVERALL STATUS: HEALTHY"]
    write_report(report)
    sys.exit(0)
else:
    report += [
        "  OVERALL STATUS: DEGRADED",
        "  No active SCTP association found.",
        "  gNB is NOT registered with AMF.",
    ]
    write_report(report)
    sys.exit(1)
