"""Descarga de imágenes del host estático del SMN.

El host está detrás de Cloudflare, así que hay dos caminos:
  1. HTTP directo con httpx (rápido; funciona desde IPs no marcadas).
  2. Navegador real vía Playwright, que resuelve el desafío de Cloudflare.

Siempre se descargan los bytes originales del JPG: nunca capturas de pantalla.
"""

from __future__ import annotations

import io
import time
from typing import Optional

import httpx
from PIL import Image, UnidentifiedImageError

from config import DownloadConfig, SmnConfig
from logger import get_logger

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_IMAGE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": "https://www.smn.gob.ar/",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
}

_MIN_IMAGE_BYTES = 2048
_CHALLENGE_MARKERS = (b"just a moment", b"un momento", b"cf-mitigated", b"<html")


class ImageDownloader:
    """Descarga y valida una imagen del host estático del SMN."""

    def __init__(self, smn: SmnConfig, download: DownloadConfig, client: httpx.Client) -> None:
        self._smn = smn
        self._download = download
        self._client = client
        self._browser: Optional["_BrowserSession"] = None
        self._browser_unavailable = False

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def download(self, filename: str) -> Optional[bytes]:
        url = f"{self._smn.static_base_url}/{filename}"
        log = get_logger()

        for attempt in range(1, self._download.max_retries + 1):
            content = self._fetch_direct(url)
            if content is None and self._download.use_browser_fallback:
                content = self._fetch_with_browser(url)

            if content is not None:
                return content

            if attempt < self._download.max_retries:
                wait = 2 ** attempt
                log.warning(
                    "Descarga de %s falló (intento %s/%s). Reintento en %ss",
                    filename,
                    attempt,
                    self._download.max_retries,
                    wait,
                )
                time.sleep(wait)

        log.error("No se pudo descargar %s después de %s intentos", filename, self._download.max_retries)
        return None

    def _fetch_direct(self, url: str) -> Optional[bytes]:
        try:
            response = self._client.get(url, headers=_IMAGE_HEADERS)
        except httpx.HTTPError as exc:
            get_logger().debug("HTTP directo falló para %s: %s", url, exc)
            return None

        if response.status_code != 200:
            get_logger().debug("HTTP directo devolvió %s para %s", response.status_code, url)
            return None

        return _validated(response.content, url)

    def _fetch_with_browser(self, url: str) -> Optional[bytes]:
        if self._browser_unavailable:
            return None
        if self._browser is None:
            try:
                self._browser = _BrowserSession(headless=not self._download.developer_mode)
            except Exception as exc:  # noqa: BLE001 - Playwright puede no estar instalado
                self._browser_unavailable = True
                get_logger().error(
                    "No se pudo iniciar el navegador de respaldo (%s). "
                    "Instalá Playwright con: python -m playwright install chromium",
                    exc,
                )
                return None

        try:
            content = self._browser.fetch(url, timeout_seconds=self._download.request_timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - una sesión rota no debe frenar el ciclo
            get_logger().warning("El navegador de respaldo falló para %s: %s", url, exc)
            self.close()
            return None

        return _validated(content, url) if content else None


def _validated(content: bytes, url: str) -> Optional[bytes]:
    """Confirma que los bytes sean realmente una imagen y no una página de error."""
    log = get_logger()
    if len(content) < _MIN_IMAGE_BYTES:
        head = content[:200].lower()
        if any(marker in head for marker in _CHALLENGE_MARKERS):
            log.debug("El servidor devolvió una página de desafío para %s", url)
        else:
            log.debug("Respuesta demasiado chica (%s bytes) para %s", len(content), url)
        return None

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError):
        log.debug("Los bytes recibidos para %s no son una imagen válida", url)
        return None

    return content


class _BrowserSession:
    """Navegador Chromium persistente para atravesar Cloudflare."""

    _CHALLENGE_TITLES = ("just a moment", "un momento", "attention required")

    def __init__(self, headless: bool) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        try:
            self._browser = self._playwright.chromium.launch(
                channel="chrome", headless=headless, args=launch_args
            )
        except Exception:  # noqa: BLE001 - si no hay Chrome instalado, usar el Chromium de Playwright
            self._browser = self._playwright.chromium.launch(headless=headless, args=launch_args)

        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            locale="es-AR",
            viewport={"width": 1280, "height": 800},
        )
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self._page = self._context.new_page()

    def fetch(self, url: str, timeout_seconds: float) -> Optional[bytes]:
        timeout_ms = int(timeout_seconds * 1000)
        response = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if response is None:
            return None

        if response.status == 200:
            return response.body()

        # Cloudflare interpuso un desafío: esperar a que el navegador lo resuelva
        # y volver a pedir el recurso reutilizando las cookies obtenidas.
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(2)
            if not self._is_challenge_page():
                break
        api_response = self._context.request.get(url, headers={"Referer": "https://www.smn.gob.ar/"})
        if api_response.status == 200:
            return api_response.body()
        return None

    def _is_challenge_page(self) -> bool:
        try:
            title = (self._page.title() or "").lower()
        except Exception:  # noqa: BLE001 - la página puede estar navegando
            return True
        return any(marker in title for marker in self._CHALLENGE_TITLES)

    def close(self) -> None:
        for closer in (
            getattr(self, "_context", None),
            getattr(self, "_browser", None),
        ):
            try:
                if closer is not None:
                    closer.close()
            except Exception:  # noqa: BLE001 - cierre best-effort
                pass
        try:
            self._playwright.stop()
        except Exception:  # noqa: BLE001 - cierre best-effort
            pass
