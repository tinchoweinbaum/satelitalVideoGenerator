"""Composición de cuadros con Pillow y codificación con FFmpeg.

Cada imagen única se compone una sola vez sobre el fondo y se cachea en memoria
como PNG. Después los cuadros se envían a FFmpeg por stdin: entran exactamente
``total_frames`` imágenes y sale un video CFR de esa cantidad de cuadros, así la
duración es siempre exacta.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, List

from PIL import Image

from config import Config
from frame_plan import FramePlan
from logger import get_logger


class RenderError(Exception):
    """Falló la composición o la codificación del video."""


class VideoRenderer:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._ffmpeg = shutil.which("ffmpeg")
        if not self._ffmpeg:
            raise RenderError("No se encontró 'ffmpeg' en el PATH del sistema")
        if not config.video.background.is_file():
            raise RenderError(f"No se encontró la imagen de fondo: {config.video.background}")

    def render(self, plan: FramePlan) -> Path:
        video = self._config.video
        output_path = self._config.output.file_path(video.extension)
        temp_path = self._config.output.temp_file_path(video.extension)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        log = get_logger()
        log.info(
            "Componiendo %s cuadros (%s imágenes únicas) para %ss a %s fps",
            plan.total_frames,
            len(plan.unique_images()),
            video.duration_seconds,
            video.fps,
        )
        encoded_frames = self._compose_frames(plan)

        command = self._ffmpeg_command(temp_path, plan.total_frames)
        log.debug("Comando FFmpeg: %s", " ".join(command))

        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        assert process.stdin is not None and process.stderr is not None

        # stderr se lee en paralelo: si FFmpeg llenara la tubería de errores
        # mientras nosotros escribimos cuadros, el proceso quedaría trabado.
        stderr_chunks: List[bytes] = []
        stderr_reader = threading.Thread(
            target=lambda pipe: stderr_chunks.append(pipe.read()), args=(process.stderr,)
        )
        stderr_reader.start()

        try:
            for frame_path in plan.frames:
                process.stdin.write(encoded_frames[frame_path])
        except BrokenPipeError:
            pass
        finally:
            if not process.stdin.closed:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass

        return_code = process.wait()
        stderr_reader.join()

        if return_code != 0:
            temp_path.unlink(missing_ok=True)
            stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
            raise RenderError(f"FFmpeg terminó con código {return_code}: {stderr_text[-1500:]}")

        # Reemplazo atómico: vMix nunca ve un archivo a medio escribir.
        temp_path.replace(output_path)
        size_mb = output_path.stat().st_size / (1024 * 1024)
        log.info("Video generado: %s (%.2f MB)", output_path, size_mb)
        return output_path

    def _compose_frames(self, plan: FramePlan) -> Dict[Path, bytes]:
        video = self._config.video
        with Image.open(video.background) as background:
            canvas_base = background.convert("RGB").resize(
                (video.width, video.height), Image.LANCZOS
            )

            encoded: Dict[Path, bytes] = {}
            for image_path in plan.unique_images():
                encoded[image_path] = self._compose_single(image_path, canvas_base)
        return encoded

    def _compose_single(self, image_path: Path, canvas_base: Image.Image) -> bytes:
        video = self._config.video
        try:
            with Image.open(image_path) as source:
                map_image = source.convert("RGB")
                target_size = self._map_size(map_image.size)
                map_image = map_image.resize(target_size, Image.LANCZOS)
        except OSError as exc:
            raise RenderError(f"No se pudo abrir la imagen {image_path}: {exc}") from exc

        frame = canvas_base.copy()
        position = (
            (video.width - map_image.width) // 2,
            (video.height - map_image.height) // 2,
        )
        frame.paste(map_image, position)

        buffer = io.BytesIO()
        # compress_level bajo: el PNG solo viaja por una tubería local, así que
        # importa la velocidad y no el tamaño.
        frame.save(buffer, format="PNG", compress_level=1)
        return buffer.getvalue()

    def _map_size(self, source_size: tuple[int, int]) -> tuple[int, int]:
        video = self._config.video
        width, height = source_size

        if video.map_fit_mode == "contain":
            # Escala el mapa para que entre en el cuadro y después aplica el ratio.
            scale = min(video.width / width, video.height / height) * video.map_resize_ratio
        else:
            scale = video.map_resize_ratio

        return max(1, round(width * scale)), max(1, round(height * scale))

    def _ffmpeg_command(self, output_path: Path, total_frames: int) -> List[str]:
        video = self._config.video
        command = [
            self._ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-framerate",
            str(video.fps),
            "-i",
            "-",
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
            "-movflags",
            "+faststart",
        ]
        if video.codec.startswith("libx26"):
            command += ["-preset", video.preset]
        if video.threads > 0:
            command += ["-threads", str(video.threads)]
        command.append(str(output_path))
        return command
