#!/usr/bin/env python3
"""
provision_slice.py
──────────────────
JOB 2 script — Patches AMF, SMF or gNB configmaps with new slice config.
Called once per target: --target amf / smf / gnb
Exits 0 = patched successfully, Exits 1 = failed.
"""
import argparse
import sys
import yaml
from kubernetes import client, config as k8s_config

# ── Init kubernetes client ────────────────────────────────────
k8s_config.load_kube_config()
v1 = client.CoreV1Api()
NAMESPACE = "oai5g"

def load_slice(filepath: str) -> dict:
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]

# ── AMF Patch ─────────────────────────────────────────────────
def patch_amf(slice: dict):
    """
    Adds new NSSAI (SST+SD) to AMF's plmn_support slice list.
    AMF uses this to accept UEs requesting this slice.
    """
    print(f"\n[AMF] Patching configmap for slice {slice['name']}...")

    cm = v1.read_namespaced_config_map("oai-amf-configmap", NAMESPACE)
    amf_cfg = yaml.safe_load(cm.data["config.yaml"])

    new_slice = {"sst": slice["sst"], "sd": slice["sd"]}
    slices = amf_cfg["amf"]["plmn_support"][0].setdefault("slice_support", [])

    if new_slice not in slices:
        slices.append(new_slice)
        cm.data["config.yaml"] = yaml.dump(amf_cfg)
        v1.patch_namespaced_config_map("oai-amf-configmap", NAMESPACE, cm)
        print(f"  ✅ AMF: added SST={slice['sst']} SD={slice['sd']}")
    else:
        print(f"  ℹ️  AMF: slice SST={slice['sst']} SD={slice['sd']} already exists")

# ── SMF Patch ─────────────────────────────────────────────────
def patch_smf(slice: dict):
    """
    Adds new DNN entry to SMF config.
    SMF uses DNN to set up PDU sessions for UEs on this slice.
    """
    print(f"\n[SMF] Patching configmap for DNN {slice['dnn']}...")

    cm = v1.read_namespaced_config_map("oai-smf-configmap", NAMESPACE)
    smf_cfg = yaml.safe_load(cm.data["config.yaml"])

    new_dnn = {
        "dnn":              slice["dnn"],
        "pdu_session_type": "IPV4",
        "ipv4_subnet":      "12.1.1.0/24",
        "sst":              slice["sst"],
        "sd":               slice["sd"]
    }

    dnns = smf_cfg["smf"].setdefault("dnns", [])
    if not any(d["dnn"] == slice["dnn"] for d in dnns):
        dnns.append(new_dnn)
        cm.data["config.yaml"] = yaml.dump(smf_cfg)
        v1.patch_namespaced_config_map("oai-smf-configmap", NAMESPACE, cm)
        print(f"  ✅ SMF: added DNN={slice['dnn']}")
    else:
        print(f"  ℹ️  SMF: DNN={slice['dnn']} already exists")

# ── gNB Patch ─────────────────────────────────────────────────
def patch_gnb(slice: dict):
    """
    Adds new NSSAI to gNB broadcast list.
    gNB advertises this slice over the air so UEs can select it.
    """
    print(f"\n[gNB] Patching configmap for slice {slice['name']}...")

    cm = v1.read_namespaced_config_map("oai-gnb-configmap", NAMESPACE)
    gnb_cfg = yaml.safe_load(cm.data["config.yaml"])

    new_nssai = {"sst": slice["sst"], "sd": slice["sd"]}
    plmn      = gnb_cfg["gNBs"][0].setdefault("plmn_list", [{}])[0]
    nssais    = plmn.setdefault("snssaiList", [])

    if new_nssai not in nssais:
        nssais.append(new_nssai)
        cm.data["config.yaml"] = yaml.dump(gnb_cfg)
        v1.patch_namespaced_config_map("oai-gnb-configmap", NAMESPACE, cm)
        print(f"  ✅ gNB: added NSSAI SST={slice['sst']} SD={slice['sd']}")
    else:
        print(f"  ℹ️  gNB: NSSAI SST={slice['sst']} already exists")

# ── Dispatch ──────────────────────────────────────────────────
TARGETS = {
    "amf": patch_amf,
    "smf": patch_smf,
    "gnb": patch_gnb
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Provision 5G slice on OAI CNFs")
    parser.add_argument("--slice",  required=True, help="Path to slice YAML file")
    parser.add_argument("--target", required=True, choices=TARGETS.keys(),
                        help="Which NF configmap to patch")
    args = parser.parse_args()

    try:
        slice_cfg = load_slice(args.slice)
        TARGETS[args.target](slice_cfg)
    except Exception as e:
        print(f"❌ Provisioning failed for {args.target}: {e}")
        sys.exit(1)
