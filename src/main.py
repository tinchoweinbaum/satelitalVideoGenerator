"""Generador de videos de mapas satelitales para Canal 79.

Uso habitual (lo que hace run.bat): arranca el servicio y regenera el video en
los minutos configurados. Ver ``--help`` para los modos de prueba.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config, ConfigError, load_config  # noqa: E402
from logger import get_logger, setup_logging  # noqa: E402
from pipeline import Pipeline  # noqa: E402
from scheduler import Runner  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py", description="Generador de videos de mapas satelitales para Canal 79"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="genera un solo video y termina (no queda como servicio)",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="usa las imágenes que ya están en el buffer, sin consultar al SMN",
    )
    parser.add_argument(
        "--clear-buffer",
        action="store_true",
        help="vacía el buffer antes de empezar",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="valida la configuración y el entorno, sin generar nada",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="ruta alternativa a configuration.json",
    )
    return parser.parse_args()


def check_environment(config: Config) -> int:
    log = get_logger()
    problems = []

    if shutil.which("ffmpeg") is None:
        problems.append("No se encontró 'ffmpeg' en el PATH")
    if not config.video.background.is_file():
        problems.append(f"Falta la imagen de fondo: {config.video.background}")

    try:
        config.output.path.mkdir(parents=True, exist_ok=True)
        probe = config.output.path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        problems.append(f"No se puede escribir en la carpeta de salida {config.output.path}: {exc}")

    log.info("Salida: %s", config.output.file_path(config.video.extension))
    log.info(
        "Video: %sx%s, %s fps, %s s (%s cuadros)",
        config.video.width,
        config.video.height,
        config.video.fps,
        config.video.duration_seconds,
        config.video.total_frames,
    )
    log.info(
        "Secuencia: %s satélites x %s pasada(s) x (%s imágenes + %s repeticiones) = %s slots",
        len(config.satellites),
        config.sequence.sequence_repeats,
        config.sequence.buffer_size,
        config.sequence.last_image_repeats,
        config.total_slots,
    )

    for problem in problems:
        log.error(problem)

    if problems:
        return 1
    log.info("El entorno está listo")
    return 0


def main() -> int:
    args = parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    log = setup_logging(config.logging)

    if args.check:
        return check_environment(config)

    if args.clear_buffer and config.download.buffer_dir.exists():
        shutil.rmtree(config.download.buffer_dir)
        log.info("Buffer vaciado")

    try:
        with Pipeline(config) as pipeline:
            if args.once:
                pipeline.run_once(download=not args.no_download)
                return 0
            Runner(config, pipeline).run()
    except KeyboardInterrupt:
        log.info("Interrumpido por el usuario")
        return 0
    except Exception as exc:  # noqa: BLE001 - último recurso: registrar y salir con error
        log.exception("Error fatal: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
