"""Publicación segura del video final en disco.

En Windows, vMix u otro reproductor suele mantener ``mapas.mp4`` abierto en
lectura. Un ``os.replace`` normal falla con WinError 5. Este módulo reintenta y,
en Windows, usa la API ``ReplaceFile`` que puede reemplazar archivos en uso.
"""

from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

from logger import get_logger


class OutputPublishError(Exception):
    """No se pudo publicar el video en la ruta de salida configurada."""


def publish_video(
    temp_path: Path,
    output_path: Path,
    *,
    retries: int = 8,
    retry_delay_seconds: float = 2.0,
    fallback_path: Path | None = None,
) -> Path:
    """Mueve el archivo temporal al destino final.

    Devuelve la ruta donde quedó el video publicado (normalmente ``output_path``,
    o la ruta de respaldo si el destino estaba bloqueado).
    """
    log = get_logger()

    if not temp_path.is_file():
        raise OutputPublishError(f"No se encontró el archivo temporal: {temp_path}")
    if temp_path.stat().st_size <= 0:
        raise OutputPublishError(f"El archivo temporal está vacío: {temp_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _clear_readonly(output_path)

    attempts = max(1, retries)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            if _try_publish(temp_path, output_path):
                temp_path.unlink(missing_ok=True)
                return output_path
        except OSError as exc:
            last_error = exc
            log.warning(
                "No se pudo reemplazar %s (intento %s/%s): %s",
                output_path,
                attempt,
                attempts,
                exc,
            )

        if attempt < attempts:
            time.sleep(retry_delay_seconds)

    if fallback_path is not None:
        log.warning(
            "El destino %s sigue bloqueado (¿vMix u otro programa lo tiene abierto?). "
            "Guardando el video en: %s",
            output_path,
            fallback_path,
        )
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        _clear_readonly(fallback_path)
        if _try_publish(temp_path, fallback_path):
            temp_path.unlink(missing_ok=True)
            log.warning(
                "El video quedó en %s. Cerrá vMix o liberá %s para que el próximo "
                "ciclo pueda escribir ahí, o apuntá vMix al archivo de respaldo.",
                fallback_path,
                output_path,
            )
            return fallback_path

    temp_path.unlink(missing_ok=True)
    message = (
        f"No se pudo publicar el video en {output_path}. "
        "Probablemente otro programa (vMix, un reproductor o el Explorador de "
        "archivos con vista previa) tiene el archivo abierto. "
        "Cerralo o desactivá la vista previa de videos en esa carpeta."
    )
    if last_error is not None:
        raise OutputPublishError(f"{message} Detalle: {last_error}") from last_error
    raise OutputPublishError(message)


def _try_publish(temp_path: Path, output_path: Path) -> bool:
    if sys.platform == "win32" and output_path.exists():
        if _replace_file_windows(temp_path, output_path):
            return True

    if not output_path.exists():
        temp_path.replace(output_path)
        return True

    backup_path = output_path.with_suffix(output_path.suffix + ".old")
    _clear_readonly(backup_path)
    backup_path.unlink(missing_ok=True)

    try:
        output_path.replace(backup_path)
        temp_path.replace(output_path)
        backup_path.unlink(missing_ok=True)
        return True
    except OSError:
        backup_path.unlink(missing_ok=True)
        raise


def _replace_file_windows(temp_path: Path, output_path: Path) -> bool:
    """Usa ReplaceFileW: en Windows puede reemplazar archivos abiertos en lectura."""
    if sys.platform != "win32":
        return False

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    replaced = wintypes.LPCWSTR(str(output_path.resolve()))
    replacement = wintypes.LPCWSTR(str(temp_path.resolve()))
    if not kernel32.ReplaceFileW(replaced, replacement, None, 0, None, None):
        error_code = kernel32.GetLastError()
        get_logger().debug("ReplaceFileW falló con código %s", error_code)
        return False
    return True


def _clear_readonly(path: Path) -> None:
    if not path.exists():
        return
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass

    if sys.platform != "win32":
        return

    import ctypes
    from ctypes import wintypes

    try:
        kernel32 = ctypes.windll.kernel32
        resolved = wintypes.LPCWSTR(str(path.resolve()))
        attrs = kernel32.GetFileAttributesW(resolved)
        if attrs != 0xFFFFFFFF and attrs & 0x1:  # FILE_ATTRIBUTE_READONLY
            kernel32.SetFileAttributesW(resolved, attrs & ~0x1)
    except OSError:
        pass
