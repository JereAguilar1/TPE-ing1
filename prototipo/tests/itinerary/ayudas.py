"""Constantes y funciones de prueba de `itinerary` (las fábricas con fixtures están en conftest)."""

from datetime import datetime, timezone
from uuid import UUID

USUARIO = UUID("00000000-0000-4000-8000-000000000001")
RESERVA = UUID("00000000-0000-4000-8000-0000000000aa")
CREADA_EN = datetime(2026, 11, 1, tzinfo=timezone.utc)


def instante(dia: int, hora: int = 12) -> datetime:
    return datetime(2026, 11, dia, hora, tzinfo=timezone.utc)
