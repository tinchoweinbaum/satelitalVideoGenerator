"""Carga y validación de configuration.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

CONFIG_FILENAME = "configuration.json"


class ConfigError(Exception):
    """La configuración es inválida o falta un valor obligatorio."""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class VideoConfig:
    width: int
    height: int
    fps: int
    duration_seconds: int
    codec: str
    bitrate: str
    preset: str
    pixel_format: str
    extension: str
    threads: int
    background: Path

    @property
    def total_frames(self) -> int:
        return self.fps * self.duration_seconds


@dataclass(frozen=True)
class MapConfig:
    """Tamaño del mapa que se compone sobre el fondo.

    ``width`` y ``height`` definen la caja en la que entra el mapa y ``scale`` la
    agranda o achica sin tocar la caja. El mapa siempre queda centrado en el cuadro.
    """

    width: int
    height: int
    scale: float
    fit_mode: str

    def target_size(self, source_size: tuple[int, int]) -> tuple[int, int]:
        """Tamaño final del mapa para una imagen de origen dada."""
        source_width, source_height = source_size

        if self.fit_mode == "stretch":
            width = self.width * self.scale
            height = self.height * self.scale
        else:
            # 'contain': entra completo en la caja sin deformarse.
            ratio = min(self.width / source_width, self.height / source_height) * self.scale
            width = source_width * ratio
            height = source_height * ratio

        return max(1, round(width)), max(1, round(height))


@dataclass(frozen=True)
class OutputConfig:
    path: Path
    file_name: str

    def file_path(self, extension: str) -> Path:
        return self.path / f"{self.file_name}{extension}"

    def temp_file_path(self, extension: str) -> Path:
        return self.path / f".{self.file_name}.tmp{extension}"


@dataclass(frozen=True)
class SequenceConfig:
    buffer_size: int
    sequence_repeats: int
    last_image_repeats: int

    @property
    def slots_per_pass(self) -> int:
        return self.buffer_size + self.last_image_repeats


@dataclass(frozen=True)
class Satellite:
    name: str
    group_id: str


@dataclass(frozen=True)
class SmnConfig:
    api_base_url: str
    static_base_url: str
    username: str
    password: str
    token_server_url: str


@dataclass(frozen=True)
class DownloadConfig:
    buffer_dir: Path
    request_timeout_seconds: float
    max_retries: int
    delay_between_downloads_seconds: float
    use_browser_fallback: bool
    developer_mode: bool


@dataclass(frozen=True)
class ScheduleConfig:
    run_on_start: bool
    cron_minutes: List[int]


@dataclass(frozen=True)
class LoggingConfig:
    file: Path
    level: str
    email_on_error: bool
    emails_file: Path
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str


@dataclass(frozen=True)
class Config:
    video: VideoConfig
    map: MapConfig
    output: OutputConfig
    sequence: SequenceConfig
    satellites: List[Satellite]
    smn: SmnConfig
    download: DownloadConfig
    schedule: ScheduleConfig
    logging: LoggingConfig
    source_path: Path = field(default_factory=lambda: project_root() / CONFIG_FILENAME)

    @property
    def total_slots(self) -> int:
        return len(self.satellites) * self.sequence.sequence_repeats * self.sequence.slots_per_pass


def _section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"Falta la sección '{name}' en {CONFIG_FILENAME}")
    return value


def _require(section: Dict[str, Any], key: str, section_name: str) -> Any:
    if key not in section:
        raise ConfigError(f"Falta la clave '{section_name}.{key}' en {CONFIG_FILENAME}")
    return section[key]


def _resolve(root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else root / path


def load_config(path: Path | None = None) -> Config:
    root = project_root()
    config_path = path or (root / CONFIG_FILENAME)

    try:
        with open(config_path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"No se encontró {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{CONFIG_FILENAME} tiene JSON inválido: {exc}") from exc

    video_raw = _section(data, "video")
    video = VideoConfig(
        width=int(video_raw.get("width", 1920)),
        height=int(video_raw.get("height", 1080)),
        fps=int(video_raw.get("fps", 30)),
        duration_seconds=int(video_raw.get("durationSeconds", 30)),
        codec=str(video_raw.get("codec", "libx264")),
        bitrate=str(video_raw.get("bitrate", "5000k")),
        preset=str(video_raw.get("preset", "veryfast")),
        pixel_format=str(video_raw.get("pixelFormat", "yuv420p")),
        extension=str(video_raw.get("extension", ".mp4")),
        threads=int(video_raw.get("threads", 0)),
        background=_resolve(root, str(video_raw.get("background", "src/resources/background.jpg"))),
    )

    map_raw = data.get("map")
    if not isinstance(map_raw, dict):
        raise ConfigError(f"Falta la sección 'map' en {CONFIG_FILENAME}")
    map_config = MapConfig(
        width=int(map_raw.get("width", 900)),
        height=int(map_raw.get("height", 700)),
        scale=float(map_raw.get("scale", 1.0)),
        fit_mode=str(map_raw.get("fitMode", "contain")).lower(),
    )

    output_raw = _section(data, "output")
    output = OutputConfig(
        path=Path(str(_require(output_raw, "path", "output"))),
        file_name=str(_require(output_raw, "fileName", "output")),
    )

    sequence_raw = _section(data, "sequence")
    sequence = SequenceConfig(
        buffer_size=int(sequence_raw.get("bufferSize", 24)),
        sequence_repeats=int(sequence_raw.get("sequenceRepeats", 1)),
        last_image_repeats=int(sequence_raw.get("lastImageRepeats", 5)),
    )

    satellites_raw = data.get("satellites")
    if not isinstance(satellites_raw, list) or not satellites_raw:
        raise ConfigError("La sección 'satellites' debe ser una lista con al menos un satélite")
    satellites = [
        Satellite(
            name=str(_require(item, "name", "satellites")),
            group_id=str(_require(item, "groupId", "satellites")),
        )
        for item in satellites_raw
    ]

    smn_raw = _section(data, "smn")
    smn = SmnConfig(
        api_base_url=str(smn_raw.get("apiBaseUrl", "https://api-test.smn.gob.ar/v1")).rstrip("/"),
        static_base_url=str(
            smn_raw.get("staticBaseUrl", "https://estaticos.smn.gob.ar/vmsr/satelite")
        ).rstrip("/"),
        username=os.environ.get("SMN_USERNAME", str(smn_raw.get("username", ""))),
        password=os.environ.get("SMN_PASSWORD", str(smn_raw.get("password", ""))),
        token_server_url=str(smn_raw.get("tokenServerUrl", "")),
    )

    download_raw = _section(data, "download")
    download = DownloadConfig(
        buffer_dir=_resolve(root, str(download_raw.get("bufferDir", "buffer"))),
        request_timeout_seconds=float(download_raw.get("requestTimeoutSeconds", 30)),
        max_retries=int(download_raw.get("maxRetries", 3)),
        delay_between_downloads_seconds=float(download_raw.get("delayBetweenDownloadsSeconds", 1.0)),
        use_browser_fallback=bool(download_raw.get("useBrowserFallback", True)),
        developer_mode=bool(download_raw.get("developerMode", False)),
    )

    schedule_raw = _section(data, "schedule")
    schedule = ScheduleConfig(
        run_on_start=bool(schedule_raw.get("runOnStart", True)),
        cron_minutes=[int(minute) for minute in schedule_raw.get("cronMinutes", [7, 17, 27, 37, 47, 57])],
    )

    logging_raw = _section(data, "logging")
    log_config = LoggingConfig(
        file=_resolve(root, str(logging_raw.get("file", "log.txt"))),
        level=str(logging_raw.get("level", "INFO")).upper(),
        email_on_error=bool(logging_raw.get("emailOnError", False)),
        emails_file=_resolve(root, str(logging_raw.get("emailsFile", "emails.json"))),
        smtp_host=str(logging_raw.get("smtpHost", "smtp.gmail.com")),
        smtp_port=int(logging_raw.get("smtpPort", 587)),
        smtp_user=os.environ.get("SMN_SMTP_USER", str(logging_raw.get("smtpUser", ""))),
        smtp_password=os.environ.get("SMN_SMTP_PASSWORD", str(logging_raw.get("smtpPassword", ""))),
    )

    config = Config(
        video=video,
        map=map_config,
        output=output,
        sequence=sequence,
        satellites=satellites,
        smn=smn,
        download=download,
        schedule=schedule,
        logging=log_config,
        source_path=config_path,
    )
    _validate(config)
    return config


def _validate(config: Config) -> None:
    video = config.video
    if video.width <= 0 or video.height <= 0:
        raise ConfigError("video.width y video.height deben ser mayores a cero")
    if video.width % 2 or video.height % 2:
        raise ConfigError("video.width y video.height deben ser pares (requisito de H.264/yuv420p)")
    if video.fps <= 0:
        raise ConfigError("video.fps debe ser mayor a cero")
    if video.duration_seconds <= 0:
        raise ConfigError("video.durationSeconds debe ser mayor a cero")
    if not video.extension.startswith("."):
        raise ConfigError("video.extension debe empezar con un punto, por ejemplo '.mp4'")

    map_config = config.map
    if map_config.width <= 0 or map_config.height <= 0:
        raise ConfigError("map.width y map.height deben ser mayores a cero")
    if map_config.scale <= 0:
        raise ConfigError("map.scale debe ser mayor a cero")
    if map_config.fit_mode not in {"contain", "stretch"}:
        raise ConfigError("map.fitMode debe ser 'contain' o 'stretch'")

    scaled_width = map_config.width * map_config.scale
    scaled_height = map_config.height * map_config.scale
    if scaled_width > video.width or scaled_height > video.height:
        raise ConfigError(
            f"El mapa ({scaled_width:.0f}x{scaled_height:.0f} después de aplicar map.scale) "
            f"no entra en el video de {video.width}x{video.height}. "
            "Bajá map.width, map.height o map.scale."
        )

    sequence = config.sequence
    if sequence.buffer_size <= 0:
        raise ConfigError("sequence.bufferSize debe ser mayor a cero")
    if sequence.sequence_repeats <= 0:
        raise ConfigError("sequence.sequenceRepeats debe ser mayor a cero")
    if sequence.last_image_repeats < 0:
        raise ConfigError("sequence.lastImageRepeats no puede ser negativo")

    # Cada slot lógico tiene que recibir al menos un cuadro real, si no habría
    # imágenes que nunca aparecerían en el video.
    if config.total_slots > video.total_frames:
        raise ConfigError(
            f"La secuencia pide {config.total_slots} imágenes pero el video solo tiene "
            f"{video.total_frames} cuadros ({video.fps} fps x {video.duration_seconds} s). "
            "Reducí sequence.bufferSize o sequence.sequenceRepeats, o subí video.durationSeconds."
        )

    for minute in config.schedule.cron_minutes:
        if not 0 <= minute <= 59:
            raise ConfigError(f"schedule.cronMinutes tiene un valor inválido: {minute}")
