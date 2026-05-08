#!/usr/bin/env python3
"""
provision_slice.py — patches oai-5g-basic and oai-gnb-configmap
"""
import argparse, sys, yaml
from kubernetes import client, config as k8s_config

k8s_config.load_kube_config()
v1        = client.CoreV1Api()
NAMESPACE = "oai5g"

def load_slice(filepath):
    with open(filepath) as f:
        return yaml.safe_load(f)["slice"]

def load_cm(name):
    cm  = v1.read_namespaced_config_map(name, NAMESPACE)
    cfg = yaml.safe_load(cm.data["config.yaml"])
    return cm, cfg

def save_cm(cm, cfg):
    cm.data["config.yaml"] = yaml.dump(cfg, default_flow_style=False)
    v1.patch_namespaced_config_map(cm.metadata.name, NAMESPACE, cm)

# ── Patch oai-5g-basic ───────────────────────────────────────
def patch_5g_basic(slice):
    print(f"\n[oai-5g-basic] Patching for slice {slice['name']}...")
    cm, cfg = load_cm("oai-5g-basic")

    new_nssai = {"sst": slice["sst"], "sd": slice["sd"]}
    new_dnn   = slice["dnn"]
    changed   = False

    # 1. snssais — global slice anchor list
    snssais = cfg.setdefault("snssais", [])
    if new_nssai not in snssais:
        snssais.append(new_nssai)
        print(f"  ✅ snssais: added SST={slice['sst']} SD={slice['sd']}")
        changed = True
    else:
        print(f"  ℹ️  snssais: already exists")

    # 2. amf.plmn_support_list[0].nssai — AMF accepted slices
    amf_nssai = cfg["amf"]["plmn_support_list"][0].setdefault("nssai", [])
    if new_nssai not in amf_nssai:
        amf_nssai.append(new_nssai)
        print(f"  ✅ amf.plmn_support_list.nssai: added")
        changed = True
    else:
        print(f"  ℹ️  amf.plmn_support_list.nssai: already exists")

    # 3. smf.smf_info.sNssaiSmfInfoList — SMF slice+DNN mapping
    smf_info_list = cfg["smf"]["smf_info"].setdefault("sNssaiSmfInfoList", [])
    if not any(e.get("sNssai") == new_nssai for e in smf_info_list):
        smf_info_list.append({
            "sNssai": new_nssai,
            "dnnSmfInfoList": [{"dnn": new_dnn}]
        })
        print(f"  ✅ smf.smf_info.sNssaiSmfInfoList: added DNN={new_dnn}")
        changed = True
    else:
        print(f"  ℹ️  smf.smf_info.sNssaiSmfInfoList: already exists")

    # 4. smf.local_subscription_infos — QoS profiles per slice
    sub_infos = cfg["smf"].setdefault("local_subscription_infos", [])
    if not any(e.get("dnn") == new_dnn for e in sub_infos):
        sub_infos.append({
            "single_nssai": new_nssai,
            "dnn":          new_dnn,
            "qos_profile": {
                "5qi":              9,
                "session_ambr_ul":  f"{slice.get('qos', {}).get('max_ul_mbps', 100)}Mbps",
                "session_ambr_dl":  f"{slice.get('qos', {}).get('max_dl_mbps', 200)}Mbps",
            }
        })
        print(f"  ✅ smf.local_subscription_infos: added QoS for DNN={new_dnn}")
        changed = True
    else:
        print(f"  ℹ️  smf.local_subscription_infos: already exists")

    # 5. upf.upf_info.sNssaiUpfInfoList — UPF slice routing
    upf_info_list = cfg["upf"]["upf_info"].setdefault("sNssaiUpfInfoList", [])
    if not any(e.get("sNssai") == new_nssai for e in upf_info_list):
        upf_info_list.append({
            "sNssai":        new_nssai,
            "dnnUpfInfoList": [{"dnn": new_dnn}]
        })
        print(f"  ✅ upf.upf_info.sNssaiUpfInfoList: added")
        changed = True
    else:
        print(f"  ℹ️  upf.upf_info.sNssaiUpfInfoList: already exists")

    # 6. dnns — data network definitions
    dnns = cfg.setdefault("dnns", [])
    if not any(d.get("dnn") == new_dnn for d in dnns):
        dnns.append({
            "dnn":              new_dnn,
            "pdu_session_type": "IPV4",
            "ipv4_subnet":      slice.get("ipv4_subnet", "12.2.1.0/24")
        })
        print(f"  ✅ dnns: added DNN={new_dnn} subnet={slice.get('ipv4_subnet','12.2.1.0/24')}")
        changed = True
    else:
        print(f"  ℹ️  dnns: already exists")

    if changed:
        save_cm(cm, cfg)
        print(f"  ✅ oai-5g-basic saved successfully")
    else:
        print(f"  ℹ️  No changes needed for oai-5g-basic")

# ── Patch oai-gnb-configmap ──────────────────────────────────
def patch_gnb(slice):
    print(f"\n[oai-gnb-configmap] Patching snssaiList...")
    cm, cfg = load_cm("oai-gnb-configmap")

    new_nssai = {"sst": slice["sst"], "sd": slice["sd"]}
    nssais    = cfg["gNBs"][0]["plmn_list"][0].setdefault("snssaiList", [])

    if new_nssai not in nssais:
        nssais.append(new_nssai)
        save_cm(cm, cfg)
        print(f"  ✅ oai-gnb-configmap snssaiList: added SST={slice['sst']} SD={slice['sd']}")
    else:
        print(f"  ℹ️  oai-gnb-configmap: NSSAI already exists")

TARGETS = {
    "5g-basic": patch_5g_basic,
    "gnb":      patch_gnb,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice",  required=True)
    parser.add_argument("--target", required=True, choices=TARGETS.keys())
    args = parser.parse_args()

    try:
        slice_cfg = load_slice(args.slice)
        TARGETS[args.target](slice_cfg)
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)
