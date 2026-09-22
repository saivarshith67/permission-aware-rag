# 02_keycloak_resource_creator.py
# Provision Keycloak as a local IAM surrogate for the paper's 10-bucket model
# (5 GCP RBAC + 5 AWS ABAC). Documents stay on disk; Keycloak only does authz.

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from keycloak_setup_helpers import KeycloakAdmin

load_dotenv(dotenv_path=Path.cwd() / ".env", override=True)

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
KEYCLOAK_ADMIN = os.environ.get("KEYCLOAK_ADMIN", "admin")
KEYCLOAK_ADMIN_PASSWORD = os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "admin")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "permission-aware-rag")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "permission-aware-rag-client")
KEYCLOAK_USER_PASSWORD = os.environ.get("KEYCLOAK_USER_PASSWORD", "password")

ARTIFACTS_DIR = Path("artifacts")
ACCESS_MODEL_PATH = ARTIFACTS_DIR / "generated_access_model.json"
STORAGE_MAP_PATH = ARTIFACTS_DIR / "file_to_storage_info.json"
CREDENTIAL_OUTPUT_PATH = ARTIFACTS_DIR / "test_credential.txt"
KEYCLOAK_CONFIG_PATH = ARTIFACTS_DIR / "keycloak_config.json"


def _roles_for_user(user: dict, gcp_rbac: dict, aws_abac: dict, aws_bucket_roles: dict) -> list[str]:
    """Resolve Keycloak client roles for a user from GCP roles + AWS attribute matches."""
    if user.get("full_access"):
        return list(gcp_rbac.keys()) + list(aws_bucket_roles.values())

    roles = list(user.get("gcp_roles") or [])
    attrs = user.get("aws_attributes") or {}
    for bucket, required in aws_abac.items():
        if required and all(attrs.get(k) == v for k, v in required.items()):
            role = aws_bucket_roles.get(bucket)
            if role and role not in roles:
                roles.append(role)
    return roles


def main() -> None:
    if not STORAGE_MAP_PATH.exists():
        print("[ERROR] Run scripts/03_prepare_documents.py first.")
        sys.exit(1)

    with open(ACCESS_MODEL_PATH, "r", encoding="utf-8") as f:
        access_model = json.load(f)
    with open(STORAGE_MAP_PATH, "r", encoding="utf-8") as f:
        storage_map = json.load(f)

    gcp_rbac = access_model["GCP_RBAC"]
    aws_abac = access_model["AWS_ABAC"]
    aws_bucket_roles = access_model.get("AWS_BUCKET_ROLES") or {
        bucket: f"role_read_aws_bucket_{i + 1}"
        for i, bucket in enumerate(aws_abac.keys())
    }
    users = access_model["USERS"]

    # resource/bucket -> roles that grant access
    bucket_roles: dict[str, list[str]] = {}
    for role, bucket in gcp_rbac.items():
        bucket_roles.setdefault(bucket, []).append(role)
    for bucket, role in aws_bucket_roles.items():
        bucket_roles.setdefault(bucket, []).append(role)

    all_buckets = list(gcp_rbac.values()) + list(aws_abac.keys())

    admin = KeycloakAdmin(KEYCLOAK_URL, KEYCLOAK_ADMIN, KEYCLOAK_ADMIN_PASSWORD)
    print(f"[KEYCLOAK][INFO] Waiting for Keycloak at {KEYCLOAK_URL} ...")
    admin.wait_until_ready()

    admin.create_realm(KEYCLOAK_REALM, recreate=True)
    client_uuid = admin.create_client(KEYCLOAK_REALM, KEYCLOAK_CLIENT_ID)
    admin.create_scope(KEYCLOAK_REALM, client_uuid, "read")

    # Create all roles (GCP RBAC + AWS surrogate)
    all_role_names = list(gcp_rbac.keys()) + list(aws_bucket_roles.values())
    role_ids: dict[str, str] = {}
    for role_name in all_role_names:
        role_ids[role_name] = admin.create_client_role(KEYCLOAK_REALM, client_uuid, role_name)
        print(f"[KEYCLOAK][INFO] Client role ready: {role_name}")

    role_policy_ids: dict[str, str] = {}
    for role_name, role_id in role_ids.items():
        role_policy_ids[role_name] = admin.create_role_policy(
            KEYCLOAK_REALM, client_uuid, f"policy-{role_name}", role_id, role_name
        )

    credentials = []
    for user in users:
        name = user["name"]
        roles = _roles_for_user(user, gcp_rbac, aws_abac, aws_bucket_roles)
        user_id = admin.create_user(
            KEYCLOAK_REALM,
            name,
            KEYCLOAK_USER_PASSWORD,
            attributes=user.get("aws_attributes") or {},
        )
        if roles:
            admin.assign_client_roles(KEYCLOAK_REALM, client_uuid, user_id, roles)
        print(f"[KEYCLOAK][INFO] User ready: {name} (roles={roles})")

        credentials.append(
            {
                "name": name,
                "keycloak_admin_id": KEYCLOAK_ADMIN,
                "keycloak_admin_password": KEYCLOAK_ADMIN_PASSWORD,
                "keycloak_admin_passwrod": KEYCLOAK_ADMIN_PASSWORD,
                "keycloak_user_name": name,
            }
        )

    print(
        f"[KEYCLOAK][INFO] Registering {len(all_buckets)} bucket resources "
        f"(covering {len(storage_map)} documents) ..."
    )
    for bucket in all_buckets:
        resource_id = admin.create_resource(KEYCLOAK_REALM, client_uuid, bucket, bucket)
        policy_ids = [
            role_policy_ids[r] for r in bucket_roles.get(bucket, []) if r in role_policy_ids
        ]
        if not policy_ids:
            print(f"[KEYCLOAK][WARN] No policies for bucket {bucket}")
            continue
        admin.create_resource_permission(
            KEYCLOAK_REALM, client_uuid, f"perm-{bucket}", resource_id, policy_ids
        )
        print(f"[KEYCLOAK][INFO] Bucket resource ready: {bucket}")

    keycloak_config = {
        "endpoint": KEYCLOAK_URL,
        "realm": KEYCLOAK_REALM,
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_uuid": client_uuid,
        "resource_granularity": "bucket",
        "providers_surrogate": ["gcp", "aws"],
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(KEYCLOAK_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(keycloak_config, f, indent=2)
    with open(CREDENTIAL_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(credentials, f, indent=2)

    print(f"[KEYCLOAK][INFO] Config saved to {KEYCLOAK_CONFIG_PATH}")
    print(f"[KEYCLOAK][INFO] Credentials saved to {CREDENTIAL_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
