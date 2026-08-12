"""Buffer en disco con las últimas N imágenes de cada satélite."""

from __future__ import annotations

from pathlib import Path
from typing import List

from logger import get_logger


class BufferStore:
    """Carpeta rotativa de imágenes para un satélite.

    Los nombres del SMN incluyen la fecha (``..._YYYYMMDD_HHMMSSZ.jpg``), así que
    el orden alfabético es también el orden cronológico.
    """

    def __init__(self, root: Path, satellite: str, max_images: int) -> None:
        self._directory = root / satellite
        self._satellite = satellite
        self._max_images = max_images
        self._directory.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._directory

    def existing_names(self) -> set[str]:
        return {path.name for path in self._directory.iterdir() if path.is_file()}

    def images(self) -> List[Path]:
        """Imágenes en orden cronológico (de la más vieja a la más nueva)."""
        return sorted((path for path in self._directory.iterdir() if path.is_file()), key=lambda p: p.name)

    def save(self, filename: str, content: bytes) -> Path:
        path = self._directory / filename
        temp_path = path.with_suffix(path.suffix + ".part")
        temp_path.write_bytes(content)
        temp_path.replace(path)
        get_logger().info("[%s] Imagen guardada: %s", self._satellite, filename)
        return path

    def prune(self) -> None:
        """Borra las imágenes más viejas que sobran y los restos de descargas."""
        for leftover in self._directory.glob("*.part"):
            leftover.unlink(missing_ok=True)

        images = self.images()
        for stale in images[: max(0, len(images) - self._max_images)]:
            stale.unlink(missing_ok=True)
            get_logger().debug("[%s] Imagen vieja eliminada: %s", self._satellite, stale.name)
