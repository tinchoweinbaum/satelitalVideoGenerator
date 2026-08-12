"""Armado del plan de cuadros del video.

Regla central: el video dura siempre exactamente ``fps * durationSeconds``
cuadros (30 x 30 = 900 por defecto). Para lograrlo se arma primero una lista de
"slots" lógicos (una entrada por imagen a mostrar, incluyendo las repeticiones
de la última imagen y de cada pasada) y después se reparten los cuadros reales
entre esos slots de forma pareja.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from config import SequenceConfig


class FramePlanError(Exception):
    """No hay imágenes suficientes para armar el video."""


@dataclass(frozen=True)
class FramePlan:
    """Un cuadro por posición: ``frames[i]`` es la imagen del cuadro ``i``."""

    frames: List[Path]
    slots: List[Path]
    fps: int

    @property
    def total_frames(self) -> int:
        return len(self.frames)

    @property
    def duration_seconds(self) -> float:
        return self.total_frames / self.fps

    def unique_images(self) -> List[Path]:
        seen: dict[Path, None] = {}
        for path in self.frames:
            seen.setdefault(path, None)
        return list(seen)


def build_slots(image_lists: Sequence[Sequence[Path]], sequence: SequenceConfig) -> List[Path]:
    """Arma la secuencia lógica: satélite por satélite, pasada por pasada.

    Cada pasada muestra las ``bufferSize`` imágenes en orden cronológico y
    después sostiene la última ``lastImageRepeats`` veces, igual que el programa
    original.
    """
    slots: List[Path] = []

    for images in image_lists:
        if not images:
            raise FramePlanError("Un satélite no tiene imágenes en el buffer")

        normalized = _normalize(images, sequence.buffer_size)
        pass_slots = normalized + [normalized[-1]] * sequence.last_image_repeats
        for _ in range(sequence.sequence_repeats):
            slots.extend(pass_slots)

    if not slots:
        raise FramePlanError("No hay imágenes para generar el video")
    return slots


def _normalize(images: Sequence[Path], buffer_size: int) -> List[Path]:
    """Deja exactamente ``buffer_size`` imágenes: recorta las más viejas o repite la última."""
    selected = list(images[-buffer_size:])
    while len(selected) < buffer_size:
        selected.append(selected[-1])
    return selected


def build_frame_plan(
    image_lists: Sequence[Sequence[Path]], sequence: SequenceConfig, fps: int, duration_seconds: int
) -> FramePlan:
    slots = build_slots(image_lists, sequence)
    total_frames = fps * duration_seconds

    if len(slots) > total_frames:
        raise FramePlanError(
            f"La secuencia tiene {len(slots)} imágenes pero el video solo admite {total_frames} cuadros"
        )

    # Reparto entero y parejo: el slot de cada cuadro se calcula con aritmética
    # de enteros, así la suma da exactamente total_frames sin acumular redondeos.
    slot_count = len(slots)
    frames = [slots[index * slot_count // total_frames] for index in range(total_frames)]

    return FramePlan(frames=frames, slots=slots, fps=fps)
