"""Ejecución periódica del pipeline."""

from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler

from config import Config
from logger import get_logger
from pipeline import Pipeline


class Runner:
    """Corre el pipeline al arrancar y después en los minutos configurados."""

    def __init__(self, config: Config, pipeline: Pipeline) -> None:
        self._config = config
        self._pipeline = pipeline
        self._scheduler = BlockingScheduler()

    def _job(self) -> None:
        log = get_logger()
        try:
            self._pipeline.run_once()
        except Exception as exc:  # noqa: BLE001 - un ciclo fallido no debe frenar el servicio
            log.exception("El ciclo de generación falló: %s", exc)

    def run(self) -> None:
        log = get_logger()
        minutes = ",".join(str(minute) for minute in self._config.schedule.cron_minutes)

        # El cron se registra antes del primer ciclo: así el horario queda fijo
        # aunque la generación inicial tarde varios minutos.
        self._scheduler.add_job(
            self._job,
            trigger="cron",
            minute=minutes,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
        log.info("Programado en los minutos: %s de cada hora", minutes)

        if self._config.schedule.run_on_start:
            log.info("Ejecutando el primer ciclo al arrancar")
            self._job()

        try:
            self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("Interrupción recibida, cerrando")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
