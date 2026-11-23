"""El elemento `sharing` (RF-11, RF-13, QA-12, ADR-0028): arma los módulos y define las transacciones.

* **Compartir** (`POST /viajes/{id}/comparticiones`): el viaje tiene que ser del viajero (se lee de
  `itinerary-lectura` en su nombre); vence a más tardar al fin del viaje + 30 días. Idempotente por
  `Idempotency-Key`.
* **Ver un viaje compartido** (`GET /comparticiones/{cid}`): la decisión es de `identity-access`
  (ABAC), que emite un vale de 60 s; `sharing` lo verifica y lee el viaje en nombre del dueño. Lo
  que no está permitido, no existe, venció o se revocó es el mismo `404`, y cada acceso queda
  auditado (en `identity-access`, al evaluar). La revocación surte efecto en el pedido siguiente.
* **Publicar** (`POST /viajes/{id}/publicaciones`): solo el `ResumenPublicable` que el viajero
  previsualizó y confirmó; el *gateway* lo apaga en `PicoElevado` y `DisrupcionMasiva` (ADR-0020).
"""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from fastapi import FastAPI

from trotamundos.comun.config import Configuracion, _variable
from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.comun.errores import Problema, no_encontrado
from trotamundos.comun.persistencia import (
    RespuestaGuardada,
    bloquear_usuario,
    borrar_usuario,
    crear_esquema,
    guardar_respuesta,
    huella_de_solicitud,
    respuesta_guardada,
    transaccion,
)
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos, registro_por_omision
from trotamundos.servicios.sharing import api, comparticiones, puertos, resumen
from trotamundos.servicios.sharing.complementos.red_social_simulada import RedSocialSimulada

ESQUEMA = "sharing"
DDL = comparticiones.DDL
COMPARTIR, PUBLICAR = "POST /viajes/{id}/comparticiones", "POST /viajes/{id}/publicaciones"


def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


class Sharing:
    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None, registro: RegistroDeTipos | None = None,
                 lector: puertos.LectorDeViajes | None = None,
                 autorizador: puertos.Autorizador | None = None,
                 redes: puertos.ConectorDeRedes | None = None,
                 secreto_jwt: str | None = None, secreto_vale: str | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self._registro = registro or registro_por_omision()
        self._lector = lector or puertos.LectorDeViajesHttp(
            os.environ.get("TROTAMUNDOS_URL_ITINERARY_LECTURA", "http://localhost:18102"))
        self._autorizador = autorizador or puertos.AutorizadorHttp(
            os.environ.get("TROTAMUNDOS_URL_IDENTITY_ACCESS", "http://localhost:18103"))
        self.redes = redes or RedSocialSimulada()
        self._secreto_jwt = (secreto_jwt or _variable("TROTAMUNDOS_JWT_SECRETO")
                             or secrets.token_hex(32))
        self._secreto_vale = (secreto_vale or _variable("TROTAMUNDOS_VALE_SECRETO")
                              or secrets.token_hex(32))
        self._reloj = reloj

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    # --- del dueño -----------------------------------------------------------------------

    def _viaje_propio(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any]:
        viaje = self._lector.viaje(usuario_id, viaje_id)
        if viaje is None:
            raise no_encontrado()
        return viaje

    def listar(self, usuario_id: UUID, viaje_id: UUID) -> list[dict[str, Any]]:
        self._viaje_propio(usuario_id, viaje_id)
        ahora = self._reloj()
        with self._transaccion(usuario_id) as conexion:
            return [comparticiones.a_dict(f, ahora)
                    for f in comparticiones.del_viaje(conexion, usuario_id, viaje_id)]

    def compartir(self, usuario_id: UUID, viaje_id: UUID, clave: UUID,
                  cuerpo: Mapping[str, Any]) -> dict[str, Any]:
        huella = huella_de_solicitud({"viaje": str(viaje_id), **cuerpo})
        with self._transaccion(usuario_id) as conexion:
            previa = self._previa(conexion, usuario_id, clave, COMPARTIR, huella)
            if previa is not None:
                return previa
        viaje = self._viaje_propio(usuario_id, viaje_id)
        ahora = self._reloj()
        pedido = _instante(cuerpo["expiraEn"]) if cuerpo.get("expiraEn") else None
        expira = comparticiones.vencimiento(pedido, _instante(viaje["hasta"]))
        if expira <= ahora:
            raise Problema(400, "Solicitud inválida", "La compartición vencería antes de crearse",
                           errores=[{"campo": "expiraEn", "mensaje": "ya pasó"}])
        with self._transaccion(usuario_id) as conexion:
            previa = self._previa(conexion, usuario_id, clave, COMPARTIR, huella)
            if previa is not None:
                return previa
            fila = comparticiones.crear(conexion, comparticion_id=uuid4(), usuario_id=usuario_id,
                                        viaje_id=viaje_id, designados=list(cuerpo["designados"]),
                                        expira_en=expira, ahora=ahora)
            resultado = comparticiones.a_dict(fila, ahora)
            guardar_respuesta(conexion, usuario_id, clave,
                              RespuestaGuardada(COMPARTIR, huella, 201, resultado))
        return resultado

    def revocar(self, usuario_id: UUID, viaje_id: UUID, comparticion_id: UUID) -> None:
        with self._transaccion(usuario_id) as conexion:
            if not comparticiones.revocar(conexion, usuario_id, viaje_id, comparticion_id,
                                          self._reloj()):
                raise no_encontrado()

    def previsualizar(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any]:
        return resumen.del_viaje(self._viaje_propio(usuario_id, viaje_id), self._registro)

    def publicar(self, usuario_id: UUID, viaje_id: UUID, clave: UUID,
                 cuerpo: Mapping[str, Any]) -> None:
        huella = huella_de_solicitud({"viaje": str(viaje_id), **cuerpo})
        with self._transaccion(usuario_id) as conexion:
            if self._previa(conexion, usuario_id, clave, PUBLICAR, huella) is not None:
                return
        self._viaje_propio(usuario_id, viaje_id)
        referencia = self.redes.publicar(cuerpo["red"], cuerpo["resumen"])
        with self._transaccion(usuario_id) as conexion:
            comparticiones.registrar_publicacion(
                conexion, publicacion_id=uuid4(), usuario_id=usuario_id, viaje_id=viaje_id,
                red=cuerpo["red"], referencia=referencia, ahora=self._reloj())
            guardar_respuesta(conexion, usuario_id, clave,
                              RespuestaGuardada(PUBLICAR, huella, 202, {"referencia": referencia}))

    # --- del designado -------------------------------------------------------------------

    def ver_compartido(self, sesion: Mapping[str, Any], comparticion_id: UUID) -> dict[str, Any]:
        """El viaje compartido, si `identity-access` lo permite; si no, el mismo `404`."""
        sujeto = {"usuarioId": _usuario_del_sujeto(str(sesion["sub"])),
                  "alcances": list(sesion.get("alcances") or [])}
        if sesion.get("email"):
            sujeto["correoVerificado"] = str(sesion["email"]).lower()
        vale = self._autorizador.vale(sujeto, comparticion_id)
        if vale is None or not puertos.vale_valido(vale, self._secreto_vale, comparticion_id):
            raise no_encontrado()
        with self._lectura() as conexion:
            fila = comparticiones.obtener(conexion, comparticion_id)
        if fila is None or comparticiones.estado(fila, self._reloj()) != "Activa":
            raise no_encontrado()  # revocada entre la evaluación y la lectura
        viaje = self._lector.viaje(fila["usuario_id"], fila["viaje_id"])
        if viaje is None:
            raise no_encontrado()
        return viaje

    # --- internas ------------------------------------------------------------------------

    def atributos(self, comparticion_id: UUID) -> dict[str, Any]:
        """`GET /interno/comparticiones/{cid}`, para la evaluación ABAC (ADR-0028)."""
        with self._lectura() as conexion:
            fila = comparticiones.obtener(conexion, comparticion_id)
        if fila is None:
            raise no_encontrado()
        datos = comparticiones.a_dict(fila, self._reloj())
        return {"propietarioId": str(fila["usuario_id"]), "viajeId": datos["viajeId"],
                "estado": datos["estado"], "designados": datos["designados"],
                "expiraEn": datos["expiraEn"]}

    def suprimir_usuario(self, usuario_id: UUID) -> int:
        """Orden de borrado de la fase 1 (ADR-0030, ADR-0042)."""
        with self._transaccion(usuario_id) as conexion:
            return borrar_usuario(conexion, usuario_id)

    # --- API -----------------------------------------------------------------------------

    def app(self) -> FastAPI:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def ciclo_de_vida(_: FastAPI):
            self.crear_esquema()
            yield

        return api.crear_app(self, self._contratos, self._secreto_jwt, lifespan=ciclo_de_vida)

    # --- transacciones -------------------------------------------------------------------

    def _previa(self, conexion: Any, usuario_id: UUID, clave: UUID, operacion: str,
                huella: str) -> dict[str, Any] | None:
        previa = respuesta_guardada(conexion, usuario_id, clave)
        if previa is None:
            return None
        if (previa.operacion, previa.huella) != (operacion, huella):
            raise Problema(400, "Solicitud inválida",
                           "La Idempotency-Key ya se usó con otra solicitud")
        return previa.cuerpo

    def _transaccion(self, usuario_id: UUID):
        from contextlib import contextmanager

        @contextmanager
        def con_bloqueo():
            with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
                bloquear_usuario(conexion, usuario_id)
                yield conexion
        return con_bloqueo()

    def _lectura(self):
        return transaccion(self._configuracion.dsn_postgres, self._esquema)


def _usuario_del_sujeto(sub: str) -> str:
    """El `usuarioId` para la evaluación: el del token o, para un invitado sin cuenta
    (`invitado:<correo>`), uno determinista derivado de su sujeto, solo para la auditoría."""
    try:
        return str(UUID(sub))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"trotamundos:{sub}"))


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.sharing.servicio:crear_app`."""
    return Sharing().app()
