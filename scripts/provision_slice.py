# scripts/provision_slice.py
import argparse, yaml
from kubernetes import client, config

config.load_kube_config()
v1 = client.CoreV1Api()

def load_slice(filepath):
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]

def patch_amf(slice):
    print(f"Patching AMF configmap for slice {slice['name']}...")
    cm = v1.read_namespaced_config_map("oai-amf-configmap", "oai5g")
    amf_cfg = yaml.safe_load(cm.data["config.yaml"])

    new_slice = {"sst": slice["sst"], "sd": slice["sd"]}
    slices = amf_cfg["amf"]["plmn_support"][0].setdefault("slice_support", [])
    
    if new_slice not in slices:
        slices.append(new_slice)
        cm.data["config.yaml"] = yaml.dump(amf_cfg)
        v1.patch_namespaced_config_map("oai-amf-configmap", "oai5g", cm)
        print(f"✅ AMF: added SST={slice['sst']} SD={slice['sd']}")
    else:
        print("ℹ️  AMF: slice already exists, skipping")

def patch_smf(slice):
    print(f"Patching SMF configmap for DNN {slice['dnn']}...")
    cm = v1.read_namespaced_config_map("oai-smf-configmap", "oai5g")
    smf_cfg = yaml.safe_load(cm.data["config.yaml"])

    new_dnn = {
        "dnn": slice["dnn"],
        "pdu_session_type": "IPV4",
        "ipv4_subnet": "12.1.1.0/24",
        "sst": slice["sst"],
        "sd": slice["sd"]
    }
    dnns = smf_cfg["smf"].setdefault("dnns", [])
    if not any(d["dnn"] == slice["dnn"] for d in dnns):
        dnns.append(new_dnn)
        cm.data["config.yaml"] = yaml.dump(smf_cfg)
        v1.patch_namespaced_config_map("oai-smf-configmap", "oai5g", cm)
        print(f"✅ SMF: added DNN={slice['dnn']}")

def patch_gnb(slice):
    print(f"Patching gNB configmap for slice {slice['name']}...")
    cm = v1.read_namespaced_config_map("oai-gnb-configmap", "oai5g")
    gnb_cfg = yaml.safe_load(cm.data["config.yaml"])

    new_nssai = {"sst": slice["sst"], "sd": slice["sd"]}
    nssais = gnb_cfg["gNBs"][0].setdefault("plmn_list", [{}])[0].setdefault("snssaiList", [])
    if new_nssai not in nssais:
        nssais.append(new_nssai)
        cm.data["config.yaml"] = yaml.dump(gnb_cfg)
        v1.patch_namespaced_config_map("oai-gnb-configmap", "oai5g", cm)
        print(f"✅ gNB: added NSSAI SST={slice['sst']}")

TARGETS = {"amf": patch_amf, "smf": patch_smf, "gnb": patch_gnb}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", required=True)
    parser.add_argument("--target", required=True, choices=TARGETS.keys())
    args = parser.parse_args()

    slice_cfg = load_slice(args.slice)
    TARGETS[args.target](slice_cfg)
