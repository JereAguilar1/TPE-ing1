"""`RepositorioDeReservas` en memoria para las pruebas. El de PostgreSQL es del paso 4."""

from datetime import date
from uuid import UUID

from trotamundos.comun.modelo import Fuente, Identificador
from trotamundos.servicios.itinerary.fusion.identidad import ResultadoDeIngesta, fecha_local
from trotamundos.servicios.itinerary.reservas import Reserva


class RepositorioEnMemoria:
    def __init__(self) -> None:
        self.reservas: dict[UUID, Reserva] = {}

    def guardar(self, resultado: ResultadoDeIngesta) -> None:
        for absorbida in resultado.unificadas:
            del self.reservas[absorbida.id]
        self.reservas[resultado.reserva.id] = resultado.reserva

    def del_usuario(self, usuario_id: UUID) -> list[Reserva]:
        return [r for r in self.reservas.values() if r.usuario_id == usuario_id]

    def por_identificador(self, usuario_id: UUID, identificador: Identificador) -> Reserva | None:
        return next((r for r in self.del_usuario(usuario_id) if identificador in r.identificadores),
                    None)

    def por_observacion(self, usuario_id: UUID, clave: tuple[Fuente, str]) -> Reserva | None:
        return next((r for r in self.del_usuario(usuario_id)
                     if any(o.clave == clave for o in r.observaciones)), None)

    def candidatas(self, usuario_id: UUID, desde: date, hasta: date) -> list[Reserva]:
        return [r for r in self.del_usuario(usuario_id)
                if any(desde <= fecha_local(s["inicio"]) <= hasta for s in r.vista.segmentos)]
