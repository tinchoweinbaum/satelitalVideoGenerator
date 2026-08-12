"""Orquestación: sincronizar buffers y generar el video."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

import httpx

from buffer_store import BufferStore
from config import Config
from downloader import USER_AGENT, ImageDownloader
from frame_plan import build_frame_plan
from logger import get_logger
from renderer import VideoRenderer
from smn_client import SmnClient


class PipelineError(Exception):
    """El ciclo no pudo completarse."""


class Pipeline:
    """Ciclo completo: listar, descargar, componer y codificar."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = httpx.Client(
            http2=True,
            timeout=config.download.request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self._smn = SmnClient(config.smn, self._client)
        self._downloader = ImageDownloader(config.smn, config.download, self._client)
        self._renderer = VideoRenderer(config)
        self._buffers = {
            satellite.name: BufferStore(
                config.download.buffer_dir, satellite.name, config.sequence.buffer_size
            )
            for satellite in config.satellites
        }

    def close(self) -> None:
        self._downloader.close()
        self._client.close()

    def __enter__(self) -> "Pipeline":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def sync_images(self) -> int:
        """Descarga las imágenes nuevas de cada satélite. Devuelve cuántas bajó."""
        log = get_logger()
        downloaded = 0

        for satellite in self._config.satellites:
            store = self._buffers[satellite.name]
            available = self._smn.list_images(satellite.group_id)
            if not available:
                log.warning("[%s] La API no devolvió imágenes", satellite.name)
                continue

            wanted = available[-self._config.sequence.buffer_size :]
            missing = [name for name in wanted if name not in store.existing_names()]
            log.info(
                "[%s] %s imágenes disponibles, %s por descargar",
                satellite.name,
                len(wanted),
                len(missing),
            )

            for index, filename in enumerate(missing):
                content = self._downloader.download(filename)
                if content:
                    store.save(filename, content)
                    downloaded += 1
                if index < len(missing) - 1:
                    time.sleep(self._config.download.delay_between_downloads_seconds)

            store.prune()

        return downloaded

    def image_lists(self) -> List[List[Path]]:
        lists = []
        for satellite in self._config.satellites:
            images = self._buffers[satellite.name].images()
            if not images:
                raise PipelineError(
                    f"El satélite {satellite.name} no tiene imágenes en el buffer "
                    f"({self._buffers[satellite.name].directory}). "
                    "Revisá el log: probablemente fallaron todas las descargas."
                )
            lists.append(images)
        return lists

    def render_video(self) -> Path:
        plan = build_frame_plan(
            self.image_lists(),
            self._config.sequence,
            self._config.video.fps,
            self._config.video.duration_seconds,
        )
        get_logger().info(
            "Plan de cuadros: %s slots -> %s cuadros (%.3f s)",
            len(plan.slots),
            plan.total_frames,
            plan.duration_seconds,
        )
        return self._renderer.render(plan)

    def run_once(self, download: bool = True) -> Path:
        if download:
            self.sync_images()
        return self.render_video()
