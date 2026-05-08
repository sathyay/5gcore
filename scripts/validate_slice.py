#!/usr/bin/env python3
"""
validate_slice.py
─────────────────
JOB 1 script — Validates slice YAML config before any AKS changes.
Checks required fields, data types, value ranges and PLMN format.
Exits 0 = valid, Exits 1 = invalid (pipeline stops here).
"""
import sys
import yaml
import jsonschema

# ── Schema: defines what a valid slice config must look like ──
SLICE_SCHEMA = {
    "type": "object",
    "required": ["slice"],
    "properties": {
        "slice": {
            "type": "object",
            "required": ["name", "sst", "sd", "dnn", "mcc", "mnc"],
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Unique slice name"
                },
                "sst": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 255,
                    "description": "Slice/Service Type: 1=eMBB, 2=MIoT, 3=URLLC"
                },
                "sd": {
                    "type": "string",
                    "pattern": "^0x[0-9a-fA-F]{6}$",
                    "description": "Slice Differentiator in hex format e.g. 0xFFFFFF"
                },
                "dnn": {
                    "type": "string",
                    "description": "Data Network Name (like APN in 4G)"
                },
                "mcc": {
                    "type": "string",
                    "pattern": "^[0-9]{3}$",
                    "description": "Mobile Country Code - must be 3 digits"
                },
                "mnc": {
                    "type": "string",
                    "pattern": "^[0-9]{2,3}$",
                    "description": "Mobile Network Code - must be 2 or 3 digits"
                },
                "qos": {
                    "type": "object",
                    "properties": {
                        "priority":    {"type": "string", "enum": ["low", "medium", "high"]},
                        "max_dl_mbps": {"type": "integer", "minimum": 1},
                        "max_ul_mbps": {"type": "integer", "minimum": 1},
                        "latency":     {"type": "string", "enum": ["low", "standard", "high"]}
                    }
                },
                "upf": {
                    "type": "object",
                    "properties": {
                        "dedicated": {"type": "boolean"},
                        "replicas":  {"type": "integer", "minimum": 1, "maximum": 10}
                    }
                }
            }
        }
    }
}

def validate(filepath: str):
    print(f"\n{'='*50}")
    print(f"  Validating: {filepath}")
    print(f"{'='*50}\n")

    # Load YAML
    try:
        with open(filepath) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"❌ File not found: {filepath}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"❌ Invalid YAML syntax: {e}")
        sys.exit(1)

    # Schema validation
    try:
        jsonschema.validate(config, SLICE_SCHEMA)
    except jsonschema.ValidationError as e:
        print(f"❌ Schema validation failed:")
        print(f"   Field: {' → '.join(str(p) for p in e.absolute_path)}")
        print(f"   Error: {e.message}")
        sys.exit(1)

    # Print summary of what will be provisioned
    s = config["slice"]
    print(f"  ✅ YAML syntax       : valid")
    print(f"  ✅ Schema validation  : passed")
    print(f"")
    print(f"  Slice to provision:")
    print(f"  ├─ Name  : {s['name']}")
    print(f"  ├─ SST   : {s['sst']}  (1=eMBB, 2=MIoT, 3=URLLC)")
    print(f"  ├─ SD    : {s['sd']}")
    print(f"  ├─ DNN   : {s['dnn']}")
    print(f"  ├─ PLMN  : MCC={s['mcc']} MNC={s['mnc']}")
    if "qos" in s:
        print(f"  └─ QoS   : DL={s['qos'].get('max_dl_mbps','?')}Mbps "
              f"UL={s['qos'].get('max_ul_mbps','?')}Mbps "
              f"Latency={s['qos'].get('latency','?')}")
    print(f"\n  ✅ Slice config is VALID — proceeding to provision\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: validate_slice.py <slice-file.yaml>")
        sys.exit(1)
    validate(sys.argv[1])
