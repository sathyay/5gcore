# scripts/verify_slice.py
import argparse, yaml, sys, subprocess

def load_slice(filepath):
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]

def get_logs(deployment, container):
    result = subprocess.run([
        "kubectl", "logs", "-n", "oai5g",
        f"deployment/{deployment}", "-c", container,
        "--tail=100"
    ], capture_output=True, text=True)
    return result.stdout

def check_ngap(slice):
    logs = get_logs("oai-gnb", "gnb")
    ok = "associated AMF 1" in logs
    print(f"{'✅' if ok else '❌'} NGAP registration: {'OK' if ok else 'FAILED'}")
    return ok

def check_amf_slice(slice):
    logs = get_logs("oai-amf", "amf")
    ok = f"SST={slice['sst']}" in logs or str(slice['sst']) in logs
    print(f"{'✅' if ok else '❌'} AMF slice registered: {'OK' if ok else 'FAILED'}")
    return ok

def check_pods_running():
    result = subprocess.run([
        "kubectl", "get", "pods", "-n", "oai5g",
        "-l", "app in (oai-amf,oai-smf,oai-gnb)",
        "--field-selector=status.phase=Running",
        "--no-headers"
    ], capture_output=True, text=True)
    ok = len(result.stdout.strip().splitlines()) >= 3
    print(f"{'✅' if ok else '❌'} All NF pods running: {'OK' if ok else 'FAILED'}")
    return ok

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", required=True)
    args = parser.parse_args()

    slice_cfg = load_slice(args.slice)
    results = [
        check_pods_running(),
        check_ngap(slice_cfg),
        check_amf_slice(slice_cfg),
    ]

    if all(results):
        print("\n✅ Slice provisioning VERIFIED successfully")
        sys.exit(0)
    else:
        print("\n❌ Verification FAILED — triggering rollback")
        sys.exit(1)
