# 03_prepare_documents.py
# Build per-document text files from HotpotQA and assign them across
# 5 GCP + 5 AWS buckets (paper setup). Files stay local; Keycloak is IAM only.

import json
import os
import random
import re
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

ARTIFACTS_DIR = Path("artifacts")

HOTPOT_FILE = ARTIFACTS_DIR / "hotpot_dev_distractor_v1.json"
ACCESS_MODEL_PATH = ARTIFACTS_DIR / "generated_access_model.json"
OUTPUT_BASE_DIR = ARTIFACTS_DIR / "resources"
STORAGE_MAP_OUTPUT = ARTIFACTS_DIR / "file_to_storage_info.json"

GCP_REGION = "asia-northeast3"
AWS_REGION = "ap-northeast-2"
GCP_IAM = "google iam"
AWS_IAM = "aws iam"


def _ensure_parent_dir(path_str: str) -> None:
    p = Path(path_str).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)


def sanitize_filename(title: str) -> str:
    title = title.lower().replace(" ", "_")
    return re.sub(r"[^\w\d_]", "", title)


def save_to_local(bucket_dir: str, filename: str, content: str) -> None:
    os.makedirs(bucket_dir, exist_ok=True)
    with open(os.path.join(bucket_dir, filename), "w", encoding="utf-8") as f:
        f.write(content)


def extract_documents(data: list) -> dict:
    doc_dict = {}
    for item in data:
        for title, sents in item["context"]:
            if title not in doc_dict:
                doc_dict[title] = sents
    return doc_dict


def generate_documents_and_storage_info() -> None:
    with open(HOTPOT_FILE, "r", encoding="utf-8") as f:
        hotpot_data = json.load(f)
    with open(ACCESS_MODEL_PATH, "r", encoding="utf-8") as f:
        access_model = json.load(f)

    gcp_buckets = list(access_model["GCP_RBAC"].values())
    aws_buckets = list(access_model["AWS_ABAC"].keys())
    providers = ["gcp", "aws"]

    doc_map = extract_documents(hotpot_data)
    storage_map = {}
    used_titles = set()
    count_by_provider = {"gcp": 0, "aws": 0}
    count_by_bucket = defaultdict(int)

    # Deterministic assignment for reproducible PermCov
    random.seed(42)

    for item in tqdm(hotpot_data):
        for title, _ in item["supporting_facts"]:
            if title in used_titles or title not in doc_map:
                continue
            used_titles.add(title)

            content = "\n".join(doc_map[title])
            filename = sanitize_filename(title) + ".txt"

            provider = random.choice(providers)
            if provider == "gcp":
                bucket = random.choice(gcp_buckets)
                save_to_local(
                    os.path.join(OUTPUT_BASE_DIR, "GCP", bucket), filename, content
                )
                count_by_provider["gcp"] += 1
            else:
                bucket = random.choice(aws_buckets)
                save_to_local(
                    os.path.join(OUTPUT_BASE_DIR, "AWS", bucket), filename, content
                )
                count_by_provider["aws"] += 1

            count_by_bucket[bucket] += 1
            storage_map[filename] = {
                "provider": provider,
                "bucket": bucket,
                "region": GCP_REGION if provider == "gcp" else AWS_REGION,
                "iam": GCP_IAM if provider == "gcp" else AWS_IAM,
            }

    _ensure_parent_dir(STORAGE_MAP_OUTPUT)
    with open(STORAGE_MAP_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(storage_map, f, indent=2, ensure_ascii=False)

    print("\n===== Document Storage Summary =====")
    print(f"[INFO] Total documents processed: {len(storage_map)}")
    print(f"[INFO] By provider: gcp={count_by_provider['gcp']}, aws={count_by_provider['aws']}")
    print(f"[INFO] Buckets: {len(count_by_bucket)} (paper target: 10)")
    print("\n[INFO] Documents per bucket:")
    for bucket, count in sorted(count_by_bucket.items()):
        print(f"  - {bucket}: {count} files")
    print(f"\n[INFO] Storage info saved to: {STORAGE_MAP_OUTPUT}")


if __name__ == "__main__":
    generate_documents_and_storage_info()
