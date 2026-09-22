# 04_verify_local_resources.py
# Verify local GCP/AWS document files exist (no cloud upload).

import json
import os
from pathlib import Path

ARTIFACTS_DIR = Path("artifacts")
STORAGE_MAP_FILE = ARTIFACTS_DIR / "file_to_storage_info.json"
RESOURCE_DIR = ARTIFACTS_DIR / "resources"


def verify_all() -> None:
    with open(STORAGE_MAP_FILE, "r", encoding="utf-8") as f:
        storage_map = json.load(f)

    missing = []
    verified = 0
    by_provider = {"gcp": 0, "aws": 0, "other": 0}

    for file_name, info in storage_map.items():
        provider = (info.get("provider") or "").lower()
        bucket = info["bucket"]
        if provider == "gcp":
            file_path = os.path.join(RESOURCE_DIR, "GCP", bucket, file_name)
            by_provider["gcp"] += 1
        elif provider == "aws":
            file_path = os.path.join(RESOURCE_DIR, "AWS", bucket, file_name)
            by_provider["aws"] += 1
        else:
            file_path = os.path.join(RESOURCE_DIR, "KEYCLOAK", bucket, file_name)
            by_provider["other"] += 1

        if os.path.exists(file_path):
            verified += 1
        else:
            missing.append(file_path)

    print(f"[INFO] Verified {verified}/{len(storage_map)} local files.")
    print(f"[INFO] By provider: gcp={by_provider['gcp']}, aws={by_provider['aws']}, other={by_provider['other']}")
    if missing:
        print(f"[WARN] Missing {len(missing)} files (showing first 5):")
        for path in missing[:5]:
            print(f"  - {path}")
    else:
        print("[INFO] All local resources are present. No cloud upload required.")


if __name__ == "__main__":
    verify_all()
