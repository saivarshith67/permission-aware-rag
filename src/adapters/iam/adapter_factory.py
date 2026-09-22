from typing import Dict, Type, Optional
from .base import AccessControlBase
from .keycloak import KeycloakAccessControl


class AdapterFactory:
    """IAM adapter factory.

    Local setup uses Keycloak Authorization Services as a surrogate for the
    paper's GCP (RBAC) and AWS (ABAC) providers. Provider labels from the
    storage map are preserved so metadata stays paper-compatible.
    """

    def __init__(self, credentials: Dict):
        self.credentials = credentials or {}
        self._registry: Dict[str, Type[AccessControlBase]] = {
            "keycloak": KeycloakAccessControl,
            "on-premise": KeycloakAccessControl,
            # Surrogate mappings for local Keycloak-backed paper buckets
            "gcp": KeycloakAccessControl,
            "aws": KeycloakAccessControl,
        }
        self._cache: Dict[str, AccessControlBase] = {}

    def normalize(self, provider: Optional[str]) -> str:
        return (provider or "").strip().lower()

    def get(self, provider: Optional[str]) -> Optional[AccessControlBase]:
        key = self.normalize(provider)
        adapter_cls = self._registry.get(key)
        if adapter_cls is None:
            return None
        if key not in self._cache:
            self._cache[key] = adapter_cls(self.credentials)
        return self._cache[key]

    def get_access_controller(self, provider: Optional[str]):
        return self.get(provider)
