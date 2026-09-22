"""Shared Keycloak Admin REST helpers for local provisioning."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import requests


class KeycloakAdmin:
    def __init__(self, base_url: str, admin_user: str, admin_password: str):
        self.base_url = base_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
        self._token: Optional[str] = None
        self._lock = threading.Lock()

    def _headers(self) -> Dict[str, str]:
        with self._lock:
            if not self._token:
                self._token = self._fetch_token()
            token = self._token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _fetch_token(self) -> str:
        url = f"{self.base_url}/realms/master/protocol/openid-connect/token"
        data = {
            "client_id": "admin-cli",
            "username": self.admin_user,
            "password": self.admin_password,
            "grant_type": "password",
        }
        resp = requests.post(url, data=data, timeout=30)
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Optional[Dict[str, str]] = None,
        ok_status: tuple[int, ...] = (200, 201, 204),
        _retried: bool = False,
        timeout: float = 60,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = requests.request(
            method,
            url,
            headers=self._headers(),
            json=json_body,
            params=params,
            timeout=timeout,
        )
        if resp.status_code == 401 and not _retried:
            with self._lock:
                self._token = None
            return self._request(
                method,
                path,
                json_body=json_body,
                params=params,
                ok_status=ok_status,
                _retried=True,
                timeout=timeout,
            )
        if resp.status_code not in ok_status:
            raise RuntimeError(f"{method} {path} failed ({resp.status_code}): {resp.text}")
        return resp

    def wait_until_ready(self, retries: int = 30, delay: float = 2.0) -> None:
        for _ in range(retries):
            try:
                self._fetch_token()
                return
            except Exception:
                time.sleep(delay)
        raise RuntimeError("Keycloak is not reachable. Start it with: docker compose up -d")

    def delete_realm(self, realm: str) -> None:
        """Delete realm if it exists (used for clean re-provisioning)."""
        try:
            self._request(
                "DELETE",
                f"/admin/realms/{realm}",
                ok_status=(204, 200, 404),
                timeout=300,
            )
            print(f"[KEYCLOAK][INFO] Deleted realm (if existed): {realm}")
        except RuntimeError as e:
            if "404" in str(e):
                return
            raise
        # Poll until realm is fully gone (large realms take time)
        for _ in range(60):
            try:
                resp = self._request(
                    "GET",
                    f"/admin/realms/{realm}",
                    ok_status=(200, 404),
                    timeout=30,
                )
                if resp.status_code == 404:
                    break
            except RuntimeError as e:
                if "404" in str(e):
                    break
            time.sleep(2.0)

    def create_realm(self, realm: str, *, recreate: bool = False) -> None:
        if recreate:
            # Prefer checking existence first; skip slow delete on fresh Keycloak
            try:
                resp = self._request(
                    "GET",
                    f"/admin/realms/{realm}",
                    ok_status=(200, 404),
                    timeout=30,
                )
                exists = resp.status_code == 200
            except RuntimeError as e:
                exists = "404" not in str(e)
            if exists:
                self.delete_realm(realm)
                time.sleep(1.0)
        try:
            self._request("POST", "/admin/realms", json_body={"realm": realm, "enabled": True})
            print(f"[KEYCLOAK][INFO] Created realm: {realm}")
        except RuntimeError as e:
            if "409" in str(e) or "Conflict" in str(e):
                print(f"[KEYCLOAK][INFO] Realm already exists: {realm}")
            else:
                raise

    def create_client(self, realm: str, client_id: str) -> str:
        body = {
            "clientId": client_id,
            "enabled": True,
            "publicClient": False,
            "serviceAccountsEnabled": True,
            "authorizationServicesEnabled": True,
            "directAccessGrantsEnabled": True,
            "standardFlowEnabled": True,
        }
        try:
            self._request("POST", f"/admin/realms/{realm}/clients", json_body=body)
            print(f"[KEYCLOAK][INFO] Created client: {client_id}")
        except RuntimeError as e:
            if "409" not in str(e):
                raise
            print(f"[KEYCLOAK][INFO] Client already exists: {client_id}")

        resp = self._request(
            "GET",
            f"/admin/realms/{realm}/clients",
            params={"clientId": client_id},
        )
        clients = resp.json()
        if not clients:
            raise RuntimeError(f"Client not found after create: {client_id}")
        return clients[0]["id"]

    def create_scope(self, realm: str, client_uuid: str, name: str) -> None:
        try:
            self._request(
                "POST",
                f"/admin/realms/{realm}/clients/{client_uuid}/authz/resource-server/scope",
                json_body={"name": name},
            )
        except RuntimeError as e:
            if "409" not in str(e):
                raise

    def create_client_role(self, realm: str, client_uuid: str, role_name: str) -> str:
        try:
            self._request(
                "POST",
                f"/admin/realms/{realm}/clients/{client_uuid}/roles",
                json_body={"name": role_name},
            )
        except RuntimeError as e:
            if "409" not in str(e):
                raise

        resp = self._request(
            "GET",
            f"/admin/realms/{realm}/clients/{client_uuid}/roles/{role_name}",
        )
        return resp.json()["id"]

    def create_user(
        self,
        realm: str,
        username: str,
        password: str,
        attributes: Optional[Dict[str, str]] = None,
    ) -> str:
        attrs = {k: [v] for k, v in (attributes or {}).items()}
        body: Dict[str, Any] = {
            "username": username,
            "enabled": True,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        if attrs:
            body["attributes"] = attrs

        try:
            self._request("POST", f"/admin/realms/{realm}/users", json_body=body, ok_status=(201, 204, 409))
        except RuntimeError as e:
            if "409" not in str(e):
                raise

        resp = self._request(
            "GET",
            f"/admin/realms/{realm}/users",
            params={"username": username},
        )
        users = resp.json()
        if not users:
            raise RuntimeError(f"User not found: {username}")
        return users[0]["id"]

    def assign_client_roles(
        self, realm: str, client_uuid: str, user_id: str, role_names: List[str]
    ) -> None:
        roles = []
        for name in role_names:
            resp = self._request(
                "GET",
                f"/admin/realms/{realm}/clients/{client_uuid}/roles/{name}",
            )
            roles.append(resp.json())
        self._request(
            "POST",
            f"/admin/realms/{realm}/users/{user_id}/role-mappings/clients/{client_uuid}",
            json_body=roles,
            ok_status=(204, 200),
        )

    def create_resource(
        self, realm: str, client_uuid: str, name: str, collection: str
    ) -> str:
        body = {
            "name": name,
            "displayName": name,
            "scopes": [{"name": "read"}],
            "attributes": {"collection": [collection]},
        }
        try:
            resp = self._request(
                "POST",
                f"/admin/realms/{realm}/clients/{client_uuid}/authz/resource-server/resource",
                json_body=body,
            )
            # Keycloak may return JSON with _id/id, or an empty body + Location header
            if resp.content:
                data = resp.json()
                rid = data.get("_id") or data.get("id")
                if rid:
                    return rid
            location = resp.headers.get("Location", "")
            if location:
                return location.rstrip("/").split("/")[-1]
        except RuntimeError as e:
            if "409" not in str(e):
                raise

        resp = self._request(
            "GET",
            f"/admin/realms/{realm}/clients/{client_uuid}/authz/resource-server/resource",
            params={"name": name},
        )
        for resource in resp.json():
            if resource.get("name") == name:
                return resource.get("_id") or resource.get("id")
        raise RuntimeError(f"Resource could not be resolved: {name}")

    def create_role_policy(
        self, realm: str, client_uuid: str, policy_name: str, role_id: str, role_name: str
    ) -> str:
        body = {
            "name": policy_name,
            "roles": [{"id": role_id, "required": True}],
            "logic": "POSITIVE",
        }
        try:
            resp = self._request(
                "POST",
                f"/admin/realms/{realm}/clients/{client_uuid}/authz/resource-server/policy/role",
                json_body=body,
            )
            return resp.json()["id"]
        except RuntimeError as e:
            if "409" not in str(e):
                raise
            resp = self._request(
                "GET",
                f"/admin/realms/{realm}/clients/{client_uuid}/authz/resource-server/policy",
                params={"name": policy_name},
            )
            for policy in resp.json():
                if policy.get("name") == policy_name:
                    return policy["id"]
            raise RuntimeError(f"Policy exists but could not be resolved: {policy_name}")

    def create_resource_permission(
        self,
        realm: str,
        client_uuid: str,
        permission_name: str,
        resource_id: str,
        policy_ids: List[str],
    ) -> None:
        # Resource-based permission: bind resource IDs to role policies.
        # Do not pass scope names here — Keycloak expects scope IDs if set,
        # and resource-level permissions work without explicit scopes.
        body = {
            "name": permission_name,
            "type": "resource",
            "logic": "POSITIVE",
            "decisionStrategy": "AFFIRMATIVE",
            "resources": [resource_id],
            "policies": policy_ids,
        }
        try:
            self._request(
                "POST",
                f"/admin/realms/{realm}/clients/{client_uuid}/authz/resource-server/permission/resource",
                json_body=body,
            )
        except RuntimeError as e:
            if "409" not in str(e):
                raise
