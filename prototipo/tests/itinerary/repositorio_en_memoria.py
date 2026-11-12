"""`RepositorioDeReservas` en memoria para las pruebas de la fusión. El de PostgreSQL está en
`reservas.repositorio`."""

from datetime import date
from uuid import UUID

from trotamundos.comun.modelo import Fuente, Identificador
from trotamundos.servicios.itinerary.fusion.identidad import fecha_local
from trotamundos.servicios.itinerary.reservas import Reserva


class RepositorioEnMemoria:
    def __init__(self) -> None:
        self.reservas: dict[UUID, Reserva] = {}

    def guardar(self, reserva: Reserva) -> None:
        self.reservas[reserva.id] = reserva

    def eliminar(self, reserva: Reserva) -> None:
        del self.reservas[reserva.id]

    def obtener(self, usuario_id: UUID, reserva_id: UUID) -> Reserva | None:
        reserva = self.reservas.get(reserva_id)
        return reserva if reserva is not None and reserva.usuario_id == usuario_id else None

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
