from typing import Dict, Any, Optional
import threading
import requests
from .base import AccessControlBase


class KeycloakAccessControl(AccessControlBase):
    """Keycloak Authorization Services adapter with token/user caching."""

    def __init__(self, user_credential: Dict[str, Any]):
        super().__init__(user_credential)
        self._lock = threading.Lock()
        self._admin_token: Optional[str] = None
        self._admin_token_endpoint: Optional[str] = None
        self._user_id_cache: Dict[str, Optional[str]] = {}
        self._resource_id_cache: Dict[str, Optional[str]] = {}

    def get_admin_access_token(self, keycloak_id, keycloak_password, endpoint):
        url = f"{endpoint}/realms/master/protocol/openid-connect/token"
        data = {
            "client_id": "admin-cli",
            "username": keycloak_id,
            "password": keycloak_password,
            "grant_type": "password",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        resp = requests.post(url, data=data, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json().get("access_token")

    def _get_admin_token(self, keycloak_id, keycloak_password, endpoint) -> Optional[str]:
        with self._lock:
            if self._admin_token and self._admin_token_endpoint == endpoint:
                return self._admin_token
        token = self.get_admin_access_token(keycloak_id, keycloak_password, endpoint)
        with self._lock:
            self._admin_token = token
            self._admin_token_endpoint = endpoint
        return token

    def _invalidate_admin_token(self) -> None:
        with self._lock:
            self._admin_token = None
            self._admin_token_endpoint = None

    def find_user_id_by_username(self, username, admin_token, realm, endpoint):
        url = f"{endpoint}/admin/realms/{realm}/users"
        headers = {"Authorization": f"Bearer {admin_token}"}
        params = {"username": username, "exact": "true"}

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        users_found = resp.json()

        if not users_found:
            return None

        return users_found[0]["id"]

    def find_resource_id_by_name(self, resource_name, admin_token, realm, endpoint, client_uuid):
        url = f"{endpoint}/admin/realms/{realm}/clients/{client_uuid}/authz/resource-server/resource"
        headers = {"Authorization": f"Bearer {admin_token}"}
        params = {"name": resource_name, "exactName": "true"}

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        for resource in resp.json():
            if resource.get("name") == resource_name:
                return resource.get("_id") or resource.get("id")

        return None

    def policy_evaluate(self, user_id, resource_id, resource_name, admin_token, realm, endpoint, client_uuid):
        evaluate_url = (
            f"{endpoint}/admin/realms/{realm}/clients/{client_uuid}"
            f"/authz/resource-server/policy/evaluate"
        )
        headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        data = {
            "userId": user_id,
            "clientId": client_uuid,
            "entitlements": False,
            "resources": [
                {"_id": resource_id, "name": resource_name, "scopes": [{"name": "read"}]}
            ],
        }

        resp = requests.post(evaluate_url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json().get("status") == "PERMIT"

    def check_access(self, resource_metadata: Dict[str, Any]) -> bool:
        try:
            # Prefer correctly spelled key; keep legacy typo for old credentials.
            keycloak_id = self.user_credential.get("keycloak_admin_id")
            keycloak_password = (
                self.user_credential.get("keycloak_admin_password")
                or self.user_credential.get("keycloak_admin_passwrod")
            )
            keycloak_user_name = self.user_credential.get("keycloak_user_name")

            if not (keycloak_id and keycloak_password and keycloak_user_name):
                return False

            realm = (resource_metadata.get("parameters") or {}).get("realm")
            client_uuid = (resource_metadata.get("parameters") or {}).get("client_uuid")
            # Prefer collection-level resource name (bucket); fall back to file_name
            # for older per-document Keycloak registrations.
            object_name = (
                (resource_metadata.get("parameters") or {}).get("bucket")
                or resource_metadata.get("file_name")
            )
            endpoint = resource_metadata.get("endpoint")

            if not (realm and client_uuid and object_name and endpoint):
                return False

            admin_token = self._get_admin_token(keycloak_id, keycloak_password, endpoint)
            if not admin_token:
                return False

            user_cache_key = f"{endpoint}:{realm}:{keycloak_user_name}"
            with self._lock:
                user_id = self._user_id_cache.get(user_cache_key, "__missing__")
            if user_id == "__missing__":
                try:
                    user_id = self.find_user_id_by_username(
                        keycloak_user_name, admin_token, realm, endpoint
                    )
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 401:
                        self._invalidate_admin_token()
                        admin_token = self._get_admin_token(
                            keycloak_id, keycloak_password, endpoint
                        )
                        user_id = self.find_user_id_by_username(
                            keycloak_user_name, admin_token, realm, endpoint
                        )
                    else:
                        raise
                with self._lock:
                    self._user_id_cache[user_cache_key] = user_id
            if not user_id:
                return False

            resource_cache_key = f"{endpoint}:{realm}:{client_uuid}:{object_name}"
            with self._lock:
                resource_id = self._resource_id_cache.get(resource_cache_key, "__missing__")
            if resource_id == "__missing__":
                try:
                    resource_id = self.find_resource_id_by_name(
                        object_name, admin_token, realm, endpoint, client_uuid
                    )
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 401:
                        self._invalidate_admin_token()
                        admin_token = self._get_admin_token(
                            keycloak_id, keycloak_password, endpoint
                        )
                        resource_id = self.find_resource_id_by_name(
                            object_name, admin_token, realm, endpoint, client_uuid
                        )
                    else:
                        raise
                with self._lock:
                    self._resource_id_cache[resource_cache_key] = resource_id
            if not resource_id:
                return False

            try:
                return self.policy_evaluate(
                    user_id, resource_id, object_name, admin_token, realm, endpoint, client_uuid
                )
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 401:
                    self._invalidate_admin_token()
                    admin_token = self._get_admin_token(
                        keycloak_id, keycloak_password, endpoint
                    )
                    return self.policy_evaluate(
                        user_id,
                        resource_id,
                        object_name,
                        admin_token,
                        realm,
                        endpoint,
                        client_uuid,
                    )
                raise
        except Exception:
            return False
