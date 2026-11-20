"""Composición de cuadros con Pillow y codificación con FFmpeg.

Cada imagen única se compone una sola vez y se guarda en disco como JPEG.
FFmpeg lee una lista concat agrupada por duraciones (48 imágenes, no 900
decodificaciones) y x264 corre en un solo hilo, sin lookahead. Así Python y
el encoder no retienen 900 PNG Full HD ni buffers extra de x264.
"""

from __future__ import annotations

import gc
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from config import Config
from frame_plan import FramePlan
from logger import get_logger
from output_publisher import OutputPublishError, publish_video

# En la PC de playout x264 con varios hilos se queda sin RAM aunque el
# malloc pida apenas 7-11 MB: el proceso de 32 bits (o el heap ya fragmentado)
# no puede servir ese bloque. Un hilo, ultrafast y sin lookahead es el piso.
_DEFAULT_ENCODER_THREADS = 1
_MAX_ENCODER_THREADS = 1
_JPEG_QUALITY = 92
_LOW_MEM_X264_PARAMS = (
    "threads=1:sliced-threads=0:sync-lookahead=0:rc-lookahead=0:"
    "lookahead-threads=1:ref=1:bframes=0:scenecut=0:mbtree=0"
)


class RenderError(Exception):
    """Falló la composición o la codificación del video."""


class VideoRenderer:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._ffmpeg = shutil.which("ffmpeg")
        if not self._ffmpeg:
            raise RenderError("No se encontró 'ffmpeg' en el PATH del sistema")
        _warn_if_32bit_ffmpeg(self._ffmpeg)
        if config.video.mapas_fondo:
            if not config.video.foreground.is_file():
                raise RenderError(
                    f"No se encontró la imagen de primer plano: {config.video.foreground}"
                )
        elif not config.video.background.is_file():
            raise RenderError(f"No se encontró la imagen de fondo: {config.video.background}")
        configured = config.video.threads
        if configured > _MAX_ENCODER_THREADS:
            get_logger().info(
                "video.threads=%s se limita a %s para no quedarse sin RAM al codificar",
                configured,
                _MAX_ENCODER_THREADS,
            )

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
        gc.collect()
        command = self._ffmpeg_command(concat_path, output_path, total_frames)
        get_logger().debug("Comando FFmpeg: %s", " ".join(command))
        completed = subprocess.run(command, capture_output=True)
        if completed.returncode != 0:
            stderr_text = completed.stderr.decode("utf-8", errors="replace")
            raise RenderError(_format_ffmpeg_error(completed.returncode, stderr_text))

    def _encoder_threads(self) -> int:
        configured = self._config.video.threads
        if configured > 0:
            return min(configured, _MAX_ENCODER_THREADS)
        return _DEFAULT_ENCODER_THREADS

    def _ffmpeg_command(self, concat_path: Path, output_path: Path, total_frames: int) -> List[str]:
        video = self._config.video
        threads = str(self._encoder_threads())
        command = [
            self._ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            threads,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-an",
            "-vsync",
            "cfr",
            "-r",
            str(video.fps),
            "-frames:v",
            str(total_frames),
            "-c:v",
            video.codec,
            "-b:v",
            video.bitrate,
            "-pix_fmt",
            video.pixel_format,
            "-threads",
            threads,
            "-max_muxing_queue_size",
            "16",
            "-movflags",
            "+faststart",
        ]
        if video.codec.startswith("libx264"):
            command += [
                "-preset",
                "ultrafast",
                "-tune",
                "stillimage",
                "-x264-params",
                _LOW_MEM_X264_PARAMS,
            ]
        elif video.codec.startswith("libx26"):
            command += ["-preset", video.preset]
        command.append(str(output_path))
        return command


def _save_jpeg(frame: Image.Image, path: Path) -> None:
    frame.convert("RGB").save(path, format="JPEG", quality=_JPEG_QUALITY, optimize=False)


def _write_concat_list(plan: FramePlan, unique_files: Dict[Path, Path], concat_path: Path) -> None:
    """Una entrada por racha de cuadros iguales, con duración en segundos.

    El demuxer concat exige repetir el último archivo. Las rutas son relativas
    al archivo concat (nombres cortos).
    """
    groups = _group_consecutive_frames(plan.frames)
    lines = ["ffconcat version 1.0\n"]
    for source, n_frames in groups:
        jpeg_path = unique_files[source]
        duration = n_frames / plan.fps
        lines.append(f"file '{jpeg_path.name}'\n")
        lines.append(f"duration {duration:.6f}\n")
    if groups:
        last = unique_files[groups[-1][0]]
        lines.append(f"file '{last.name}'\n")
    concat_path.write_text("".join(lines), encoding="utf-8")


def _group_consecutive_frames(frames: List[Path]) -> List[tuple[Path, int]]:
    groups: List[tuple[Path, int]] = []
    current: Optional[Path] = None
    count = 0
    for source in frames:
        if source == current:
            count += 1
            continue
        if current is not None:
            groups.append((current, count))
        current = source
        count = 1
    if current is not None:
        groups.append((current, count))
    return groups


def _format_ffmpeg_error(returncode: int, stderr_text: str) -> str:
    hint = ""
    if "malloc" in stderr_text.lower():
        hint = (
            " FFmpeg se quedó sin memoria al codificar. Hace falta un FFmpeg de 64 bits "
            "(el de 32 bits falla en Full HD aunque pida 7 MB) y no dejar Chrome abierto "
            "durante el encode. "
        )
    return f"FFmpeg terminó con código {returncode}:{hint}{stderr_text[-1500:]}"


def _warn_if_32bit_ffmpeg(ffmpeg_path: str) -> None:
    warning = inspect_ffmpeg_architecture(ffmpeg_path)
    if warning:
        get_logger().warning(warning)


def inspect_ffmpeg_architecture(ffmpeg_path: str) -> Optional[str]:
    """Devuelve un aviso si FFmpeg parece de 32 bits; si no, None."""
    try:
        completed = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-buildconf"],
            capture_output=True,
            timeout=8,
        )
    except Exception:  # noqa: BLE001 - un probe fallido no debe frenar el render
        try:
            completed = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                timeout=8,
            )
        except Exception:  # noqa: BLE001
            return None

    text = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").lower()
    if any(marker in text for marker in ("x86_64", "amd64", "win64", "aarch64", "arm64")):
        return None
    if any(marker in text for marker in ("--arch=x86", "win32", "i686", "i386")):
        return (
            "FFmpeg parece de 32 bits. En Full HD x264 suele fallar con 'malloc'. "
            "Instalá un build de 64 bits (por ejemplo el essentials de gyan.dev) y "
            "asegurate de que 'where ffmpeg' apunte a ese."
        )
    return None
