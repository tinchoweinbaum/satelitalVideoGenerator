"""Composición de cuadros con Pillow y codificación con FFmpeg.

Cada imagen única se compone una sola vez y se guarda en disco como JPEG.
FFmpeg lee una lista concat (900 entradas que apuntan a esos JPEG) y codifica
a 30 fps. Así Python y x264 no tienen que retener 900 PNG Full HD en RAM.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from PIL import Image

from config import Config
from frame_plan import FramePlan
from logger import get_logger
from output_publisher import OutputPublishError, publish_video

# Si configuration.json deja threads en 0, no usar todos los núcleos: cada hilo
# de x264 reserva buffers extra y eso es lo que agotó la RAM en el estudio.
_DEFAULT_ENCODER_THREADS = 2
_JPEG_QUALITY = 92


class RenderError(Exception):
    """Falló la composición o la codificación del video."""


class VideoRenderer:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._ffmpeg = shutil.which("ffmpeg")
        if not self._ffmpeg:
            raise RenderError("No se encontró 'ffmpeg' en el PATH del sistema")
        if config.video.mapas_fondo:
            if not config.video.foreground.is_file():
                raise RenderError(
                    f"No se encontró la imagen de primer plano: {config.video.foreground}"
                )
        elif not config.video.background.is_file():
            raise RenderError(f"No se encontró la imagen de fondo: {config.video.background}")

    def render(self, plan: FramePlan) -> Path:
        video = self._config.video
        output_path = self._config.output.file_path(video.extension)
        temp_path = self._config.output.temp_file_path(video.extension)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frames_dir = output_path.parent / f".{self._config.output.file_name}_frames"

        log = get_logger()
        log.info(
            "Componiendo %s cuadros (%s imágenes únicas) para %ss a %s fps",
            plan.total_frames,
            len(plan.unique_images()),
            video.duration_seconds,
            video.fps,
        )

        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)
        frames_dir.mkdir(parents=True, exist_ok=True)

        try:
            unique_files = self._compose_frames_to_disk(plan, frames_dir)
            concat_path = frames_dir / "frames.txt"
            _write_concat_list(plan, unique_files, concat_path)
            self._run_ffmpeg(concat_path, temp_path, plan.total_frames)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

        output_cfg = self._config.output
        try:
            published_path = publish_video(
                temp_path,
                output_path,
                retries=output_cfg.replace_retries,
                retry_delay_seconds=output_cfg.replace_retry_delay_seconds,
                fallback_path=output_cfg.fallback_file_path(video.extension),
            )
        except OutputPublishError as exc:
            raise RenderError(str(exc)) from exc

        size_mb = published_path.stat().st_size / (1024 * 1024)
        log.info("Video generado: %s (%.2f MB)", published_path, size_mb)
        return published_path

    def _compose_frames_to_disk(self, plan: FramePlan, frames_dir: Path) -> Dict[Path, Path]:
        video = self._config.video
        unique_files: Dict[Path, Path] = {}
        map_sizes: set[tuple[int, int]] = set()

        if video.mapas_fondo:
            with Image.open(video.foreground) as overlay:
                foreground = overlay.convert("RGBA").resize(
                    (video.width, video.height), Image.LANCZOS
                )
            for index, image_path in enumerate(plan.unique_images()):
                frame, size = self._compose_fullscreen(image_path, foreground)
                dest = frames_dir / f"u{index:03d}.jpg"
                _save_jpeg(frame, dest)
                unique_files[image_path] = dest
                map_sizes.add(size)
            get_logger().info(
                "Modo mapas_fondo: mapa a pantalla completa %sx%s con foreground",
                video.width,
                video.height,
            )
            return unique_files

        with Image.open(video.background) as background:
            canvas_base = background.convert("RGB").resize(
                (video.width, video.height), Image.LANCZOS
            )
            for index, image_path in enumerate(plan.unique_images()):
                frame, size = self._compose_centered(image_path, canvas_base)
                dest = frames_dir / f"u{index:03d}.jpg"
                _save_jpeg(frame, dest)
                unique_files[image_path] = dest
                map_sizes.add(size)

        get_logger().info(
            "Mapa centrado en %sx%s con tamaño: %s",
            video.width,
            video.height,
            ", ".join(f"{width}x{height}" for width, height in sorted(map_sizes)),
        )
        return unique_files

    def _compose_centered(
        self, image_path: Path, canvas_base: Image.Image
    ) -> tuple[Image.Image, tuple[int, int]]:
        video = self._config.video
        try:
            with Image.open(image_path) as source:
                map_image = source.convert("RGB")
                target_size = self._config.map.target_size(map_image.size)
                map_image = map_image.resize(target_size, Image.LANCZOS)
        except OSError as exc:
            raise RenderError(f"No se pudo abrir la imagen {image_path}: {exc}") from exc

        frame = canvas_base.copy()
        position = (
            (video.width - map_image.width) // 2,
            (video.height - map_image.height) // 2,
        )
        frame.paste(map_image, position)
        return frame, (map_image.width, map_image.height)

    def _compose_fullscreen(
        self, image_path: Path, foreground: Image.Image
    ) -> tuple[Image.Image, tuple[int, int]]:
        video = self._config.video
        canvas_size = (video.width, video.height)
        try:
            with Image.open(image_path) as source:
                map_image = source.convert("RGB").resize(canvas_size, Image.LANCZOS)
        except OSError as exc:
            raise RenderError(f"No se pudo abrir la imagen {image_path}: {exc}") from exc

        frame = map_image.convert("RGBA")
        if "A" in foreground.getbands():
            frame = Image.alpha_composite(frame, foreground)
        else:
            frame.paste(foreground.convert("RGBA"), (0, 0))
        return frame.convert("RGB"), canvas_size

    def _run_ffmpeg(self, concat_path: Path, output_path: Path, total_frames: int) -> None:
        command = self._ffmpeg_command(concat_path, output_path, total_frames)
        get_logger().debug("Comando FFmpeg: %s", " ".join(command))
        completed = subprocess.run(command, capture_output=True)
        if completed.returncode != 0:
            stderr_text = completed.stderr.decode("utf-8", errors="replace")
            raise RenderError(
                f"FFmpeg terminó con código {completed.returncode}: {stderr_text[-1500:]}"
            )

    def _encoder_threads(self) -> int:
        configured = self._config.video.threads
        if configured > 0:
            return configured
        return _DEFAULT_ENCODER_THREADS

    def _ffmpeg_command(self, concat_path: Path, output_path: Path, total_frames: int) -> List[str]:
        video = self._config.video
        command = [
            self._ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-r",
            str(video.fps),
            "-i",
            str(concat_path),
            "-an",
            "-c:v",
            video.codec,
            "-b:v",
            video.bitrate,
            "-pix_fmt",
            video.pixel_format,
            "-r",
            str(video.fps),
            "-frames:v",
            str(total_frames),
            "-threads",
            str(self._encoder_threads()),
            "-movflags",
            "+faststart",
        ]
        if video.codec.startswith("libx26"):
            command += ["-preset", video.preset]
        command.append(str(output_path))
        return command


def _save_jpeg(frame: Image.Image, path: Path) -> None:
    frame.convert("RGB").save(path, format="JPEG", quality=_JPEG_QUALITY, optimize=False)


def _write_concat_list(plan: FramePlan, unique_files: Dict[Path, Path], concat_path: Path) -> None:
    """Una línea por cuadro. Las rutas son relativas al archivo concat (nombres cortos)."""
    lines = ["ffconcat version 1.0\n"]
    for source in plan.frames:
        jpeg_path = unique_files[source]
        lines.append(f"file '{jpeg_path.name}'\n")
    concat_path.write_text("".join(lines), encoding="utf-8")
