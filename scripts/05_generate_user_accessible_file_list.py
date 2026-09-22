# 05_generate_user_accessible_file_list.py
# Produce per-user visible file lists from paper GCP RBAC + AWS ABAC model.

import json
from collections import defaultdict
from pathlib import Path

ARTIFACTS_DIR = Path("artifacts")

ACCESS_MODEL_FILE = ARTIFACTS_DIR / "generated_access_model.json"
FILE_TO_STORAGE_FILE = ARTIFACTS_DIR / "file_to_storage_info.json"
OUTPUT_FILE = ARTIFACTS_DIR / "user_accessible_files.json"


def _ensure_parent_dir(path_str: str) -> None:
    p = Path(path_str).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)


def generate_access_visibility() -> None:
    with open(ACCESS_MODEL_FILE, "r", encoding="utf-8") as f:
        access_model = json.load(f)
    with open(FILE_TO_STORAGE_FILE, "r", encoding="utf-8") as f:
        file_to_storage = json.load(f)

    gcp_rbac = access_model["GCP_RBAC"]
    aws_abac = access_model["AWS_ABAC"]
    users = access_model["USERS"]

    bucket_to_files = defaultdict(list)
    for file_name, storage_info in file_to_storage.items():
        bucket_to_files[storage_info["bucket"]].append(file_name)

    user_visibility = {}

    for user in users:
        name = user["name"]

        if user.get("full_access"):
            user_visibility[name] = {"full_access": True}
            continue

        visible_files = set()

        # GCP RBAC
        for role in user.get("gcp_roles") or []:
            bucket = gcp_rbac.get(role)
            if bucket and bucket in bucket_to_files:
                visible_files.update(bucket_to_files[bucket])

        # AWS ABAC (exact attribute match)
        user_attr = user.get("aws_attributes") or {}
        for bucket, required_attr in aws_abac.items():
            if not required_attr:
                continue
            match = all(user_attr.get(k) == v for k, v in required_attr.items())
            if match and bucket in bucket_to_files:
                visible_files.update(bucket_to_files[bucket])

        user_visibility[name] = {"files": sorted(visible_files)}

    _ensure_parent_dir(OUTPUT_FILE)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(user_visibility, f, indent=2, ensure_ascii=False)

    print(f"[INFO] User-wise access visibility saved to {OUTPUT_FILE}")
    for name, info in user_visibility.items():
        if info.get("full_access"):
            print(f"  - {name}: FULL ACCESS")
        else:
            n = len(info.get("files", []))
            pct = 100.0 * n / max(1, len(file_to_storage))
            print(f"  - {name}: {n} files (~{pct:.1f}% of corpus)")


if __name__ == "__main__":
    generate_access_visibility()
