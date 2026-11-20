"""Descarga de imágenes del host estático del SMN.

El host está detrás de Cloudflare, así que hay dos caminos:
  1. HTTP directo con httpx (rápido; funciona desde IPs no marcadas).
  2. Navegador real vía Playwright, que resuelve el desafío de Cloudflare.

Siempre se descargan los bytes originales del JPG: nunca capturas de pantalla.

Si Cloudflare (o la red) falla varias veces seguidas, el ciclo se corta: no se
abre Chrome por cada archivo faltante. Eso era lo que vaciaba la RAM del estudio
antes de que FFmpeg siquiera empezara a codificar.
"""

from __future__ import annotations

import io
import time
from typing import Optional, Tuple

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
_BLOCKED_STATUS = {401, 403, 503}


class ImageDownloader:
    """Descarga y valida una imagen del host estático del SMN."""

    def __init__(self, smn: SmnConfig, download: DownloadConfig, client: httpx.Client) -> None:
        self._smn = smn
        self._download = download
        self._client = client
        self._browser: Optional["_BrowserSession"] = None
        self._browser_unavailable = False
        self._browser_gave_up = False
        self._consecutive_failures = 0
        self._skip_remaining = False

    @property
    def skipping_remaining(self) -> bool:
        """True cuando este ciclo ya cortó las descargas y debe usar el buffer."""
        return self._skip_remaining

    def begin_cycle(self) -> None:
        """Arranca un ciclo de sync: se vuelve a intentar, pero Chrome parte cerrado."""
        self._consecutive_failures = 0
        self._skip_remaining = False
        self._browser_gave_up = False
        self.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def download(self, filename: str) -> Optional[bytes]:
        if self._skip_remaining:
            return None

        url = f"{self._smn.static_base_url}/{filename}"
        log = get_logger()
        content: Optional[bytes] = None
        blocked = False

        for attempt in range(1, self._download.max_retries + 1):
            content, blocked = self._fetch_direct(url)
            if content is not None:
                break
            if blocked:
                # Cloudflare/403 no se arregla esperando 2s y 4s: no tiene sentido
                # repetir el mismo GET tres veces.
                break
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

        if content is None and self._should_use_browser():
            content = self._fetch_with_browser(url)
            if content is not None:
                self._import_browser_cookies()
            else:
                self._browser_gave_up = True
                self.close()
                log.warning(
                    "El navegador no pudo bajar %s. No se vuelve a abrir Chrome en este ciclo",
                    filename,
                )

        if content is not None:
            self._consecutive_failures = 0
            return content

        self._consecutive_failures += 1
        log.error(
            "No se pudo descargar %s después de %s intentos",
            filename,
            self._download.max_retries,
        )
        if self._consecutive_failures >= self._download.max_consecutive_failures:
            self._skip_remaining = True
            log.warning(
                "Se cortó la descarga: %s archivos fallaron seguidos. "
                "Se usa el buffer actual y no se sigue pidiendo al SMN en este ciclo",
                self._consecutive_failures,
            )
            self.close()
        return None

    def _should_use_browser(self) -> bool:
        return (
            self._download.use_browser_fallback
            and not self._browser_unavailable
            and not self._browser_gave_up
        )

    def _fetch_direct(self, url: str) -> Tuple[Optional[bytes], bool]:
        """Devuelve (bytes, bloqueado_por_cloudflare)."""
        try:
            response = self._client.get(url, headers=_IMAGE_HEADERS)
        except httpx.HTTPError as exc:
            get_logger().debug("HTTP directo falló para %s: %s", url, exc)
            return None, False

        if response.status_code in _BLOCKED_STATUS:
            get_logger().debug("HTTP directo devolvió %s para %s", response.status_code, url)
            return None, True

        if response.status_code != 200:
            get_logger().debug("HTTP directo devolvió %s para %s", response.status_code, url)
            return None, False

        if _looks_like_challenge(response.content):
            get_logger().debug("El servidor devolvió una página de desafío para %s", url)
            return None, True

        return _validated(response.content, url), False

    def _fetch_with_browser(self, url: str) -> Optional[bytes]:
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

    def _import_browser_cookies(self) -> None:
        if self._browser is None:
            return
        try:
            for cookie in self._browser.cookies():
                name = cookie.get("name")
                value = cookie.get("value")
                if not name or value is None:
                    continue
                domain = (cookie.get("domain") or "").lstrip(".")
                self._client.cookies.set(name, value, domain=domain or None)
        except Exception as exc:  # noqa: BLE001 - si no se copian, el HTTP directo sigue igual
            get_logger().debug("No se pudieron copiar las cookies del navegador: %s", exc)


def _looks_like_challenge(content: bytes) -> bool:
    head = content[:2048].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _validated(content: bytes, url: str) -> Optional[bytes]:
    """Confirma que los bytes sean realmente una imagen y no una página de error."""
    log = get_logger()
    if len(content) < _MIN_IMAGE_BYTES:
        if _looks_like_challenge(content):
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
        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ]
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

    def cookies(self) -> list:
        return self._context.cookies()

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
