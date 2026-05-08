# scripts/validate_slice.py
import sys, yaml, jsonschema

SCHEMA = {
    "type": "object",
    "required": ["slice"],
    "properties": {
        "slice": {
            "type": "object",
            "required": ["name", "sst", "sd", "dnn", "mcc", "mnc"],
            "properties": {
                "sst": {"type": "integer", "minimum": 1, "maximum": 255},
                "sd":  {"type": "string", "pattern": "^0x[0-9a-fA-F]{6}$"},
                "mcc": {"type": "string", "pattern": "^[0-9]{3}$"},
                "mnc": {"type": "string", "pattern": "^[0-9]{2,3}$"},
            }
        }
    }
}

def validate(filepath):
    with open(filepath) as f:
        config = yaml.safe_load(f)
    try:
        jsonschema.validate(config, SCHEMA)
        print(f"✅ Slice config valid: {filepath}")
    except jsonschema.ValidationError as e:
        print(f"❌ Invalid slice config: {e.message}")
        sys.exit(1)

if __name__ == "__main__":
    validate(sys.argv[1])
