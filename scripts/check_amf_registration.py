import subprocess, datetime, sys

NAMESPACE  = "oai5g"
GNB_LABEL  = "app=oai-gnb"
AMF_LABEL  = "app=oai-5g"
REPORT     = "amf_report.txt"

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, shell=True)

def get_pod_name(label):
    r = run(f"kubectl get pod -n {NAMESPACE} -l {label} -o jsonpath='{{.items[0].metadata.name}}'")
    return r.stdout.strip()

def get_gnb_logs(pod):
    r = run(f"kubectl logs -n {NAMESPACE} {pod} -c gnb --tail=100")
    return r.stdout

def check_sctp_assocs(pod):
    r = run(f"kubectl exec -n {NAMESPACE} {pod} -c gnb -- cat /proc/net/sctp/assocs")
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    return len(lines) > 1

def parse_associated_amf(logs):
    for line in reversed(logs.splitlines()):
        if "associated AMF" in line:
            count = line.split("associated AMF")[-1].strip().split()[0]
            return int(count)
    return -1

def pod_status(label):
    r = run(f"kubectl get pod -n {NAMESPACE} -l {label} -o jsonpath='{{.items[0].status.phase}}'")
    return r.stdout.strip()

def write_report(lines):
    content = "\n".join(lines)
    print(content)
    with open(REPORT, "w") as f:
        f.write(content)

now       = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
gnb_pod   = get_pod_name(GNB_LABEL)
amf_pod   = get_pod_name(AMF_LABEL)
gnb_logs  = get_gnb_logs(gnb_pod)
amf_count = parse_associated_amf(gnb_logs)
sctp_ok   = check_sctp_assocs(gnb_pod)
gnb_state = pod_status(GNB_LABEL)
amf_state = pod_status(AMF_LABEL)

report = [
    "=" * 50,
    "  OAI 5G AMF Registration Report",
    f"  {now}",
    "=" * 50,
    "",
    f"  gNB Pod   : {gnb_pod}",
    f"  gNB Status: {gnb_state}",
    f"  AMF Pod   : {amf_pod}",
    f"  AMF Status: {amf_state}",
    "",
    f"  SCTP Association : {'OK' if sctp_ok else 'DOWN'}",
    f"  Associated AMF   : {amf_count}",
    "",
]

if amf_count == 1 and sctp_ok:
    report += ["  OVERALL STATUS: HEALTHY"]
    write_report(report)
    sys.exit(0)
else:
    report += [
        "  OVERALL STATUS: DEGRADED",
        "  gNB is NOT registered with AMF.",
    ]
    write_report(report)
    sys.exit(1)
