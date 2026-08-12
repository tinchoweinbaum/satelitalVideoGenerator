"""Cliente de la API del SMN: autenticación y listado de imágenes.

La API solo devuelve nombres de archivo; los bytes de las imágenes viven en el
host estático (ver downloader.py).
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from typing import List, Optional

import httpx

from config import SmnConfig
from logger import get_logger

# Margen para renovar el token antes de que expire de verdad.
_TOKEN_EXPIRY_MARGIN_SECONDS = 300


class SmnAuthError(Exception):
    """No se pudo obtener un token válido del SMN."""


class TokenProvider:
    """Obtiene y cachea el JWT del SMN.

    Estrategia:
      1. Login oficial contra ``POST /api-token/auth`` con usuario y contraseña.
      2. Si falla, se pide el token al servidor de Canal 79.
    """

    def __init__(self, config: SmnConfig, client: httpx.Client) -> None:
        self._config = config
        self._client = client
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    def get_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and time.time() < self._expires_at:
            return self._token

        token = self._login() or self._fetch_from_canal79()
        if not token:
            raise SmnAuthError(
                "No se pudo obtener un token del SMN (ni por login ni por el servidor de Canal 79)"
            )

        self._token = token
        self._expires_at = _token_expiry(token) - _TOKEN_EXPIRY_MARGIN_SECONDS
        return token

    def _login(self) -> Optional[str]:
        if not self._config.username or not self._config.password:
            return None
        url = f"{self._config.api_base_url}/api-token/auth"
        try:
            response = self._client.post(
                url,
                json={"username": self._config.username, "password": self._config.password},
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            get_logger().warning("Login del SMN falló por error de red: %s", exc)
            return None

        if response.status_code != 200:
            get_logger().warning(
                "Login del SMN devolvió HTTP %s: %s", response.status_code, response.text[:200]
            )
            return None

        try:
            token = response.json().get("token")
        except json.JSONDecodeError:
            get_logger().warning("Login del SMN devolvió una respuesta que no es JSON")
            return None

        if token:
            get_logger().info("Token obtenido por login oficial del SMN")
            return str(token)
        return None

    def _fetch_from_canal79(self) -> Optional[str]:
        if not self._config.token_server_url:
            return None
        try:
            response = self._client.get(
                self._config.token_server_url, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            get_logger().warning("El servidor de tokens de Canal 79 no respondió: %s", exc)
            return None

        if response.status_code != 200:
            get_logger().warning(
                "El servidor de tokens de Canal 79 devolvió HTTP %s", response.status_code
            )
            return None

        try:
            data = json.loads(response.text.lstrip("\ufeff"))
        except json.JSONDecodeError:
            get_logger().warning("El servidor de tokens de Canal 79 devolvió JSON inválido")
            return None

        if data.get("estado") == 1 and data.get("noticias"):
            token = data["noticias"][0].get("token")
            if token:
                get_logger().info("Token obtenido del servidor de Canal 79")
                return str(token)
        return None


def _token_expiry(token: str) -> float:
    """Lee el campo ``exp`` del JWT. Si no se puede, asume una hora de validez."""
    try:
        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
        return float(payload["exp"])
    except (IndexError, KeyError, ValueError, binascii.Error, json.JSONDecodeError):
        return time.time() + 3600


class SmnClient:
    """Listado de imágenes disponibles por grupo de satélite."""

    def __init__(self, config: SmnConfig, client: httpx.Client) -> None:
        self._config = config
        self._client = client
        self._tokens = TokenProvider(config, client)

    @property
    def tokens(self) -> TokenProvider:
        return self._tokens

    def list_images(self, group_id: str) -> List[str]:
        """Devuelve los nombres de archivo del grupo, del más viejo al más nuevo.

        La API los entrega del más nuevo al más viejo, pero el nombre incluye la
        fecha en formato ``YYYYMMDD_HHMMSSZ``, así que ordenar alfabéticamente
        equivale a ordenar cronológicamente.
        """
        url = f"{self._config.api_base_url}/images/satellite/{group_id}"

        response = self._get_authenticated(url)
        if response.status_code in (401, 403):
            get_logger().warning("La API rechazó el token (HTTP %s). Renovando...", response.status_code)
            response = self._get_authenticated(url, force_refresh=True)

        if response.status_code == 404:
            get_logger().error("El grupo de imágenes '%s' no existe en la API del SMN", group_id)
            return []
        if response.status_code != 200:
            get_logger().error(
                "La API del SMN devolvió HTTP %s para el grupo '%s'", response.status_code, group_id
            )
            return []

        try:
            payload = response.json()
        except json.JSONDecodeError:
            get_logger().error("La API del SMN devolvió una respuesta que no es JSON para '%s'", group_id)
            return []

        names = [str(name) for name in payload.get("list", [])]
        return sorted(names)

    def _get_authenticated(self, url: str, force_refresh: bool = False) -> httpx.Response:
        token = self._tokens.get_token(force_refresh=force_refresh)
        return self._client.get(
            url, headers={"Authorization": f"JWT {token}", "Accept": "application/json"}
        )
