"""El elemento `identity-access`: arma los módulos y define las transacciones.

No es un módulo de la vista sino su punto de armado (como `itinerary/servicio.py`): coordina
sesiones OIDC, OTP de invitados, consentimiento de buzones, bóveda con cifrado por sobres
(ADR-0029), evaluación ABAC con vales JWS (ADR-0028), auditoría encadenada y supresión fase 1
(ADR-0030), además de publicar su *outbox* (`EstadoDeBuzonCambiado`, `CuentaSuprimida`).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable, Mapping
from uuid import UUID, uuid4

from fastapi import FastAPI
from psycopg.types.json import Jsonb

from trotamundos.comun.carriles import asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.comun.errores import Problema, no_encontrado
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    RespuestaGuardada,
    bloquear_usuario,
    crear_esquema,
    guardar_respuesta,
    huella_de_solicitud,
    purgar,
    respuesta_guardada,
    transaccion,
)
from trotamundos.comun.publicador import PublicadorDeOutbox
from trotamundos.servicios.identity_access import (
    api,
    auditoria_y_revocacion,
    autenticacion_oidc,
    consentimiento_buzones,
    custodia_boveda,
    motor_autorizacion_abac,
    publicacion,
)

ESQUEMA = "identity_access"
PRODUCTOR = "identity-access"
PAUSA_DEL_PUBLICADOR_S = 0.5

_registro_de_errores = logging.getLogger(__name__)

DDL = (
    *auditoria_y_revocacion.DDL,
    *custodia_boveda.DDL,
    *autenticacion_oidc.DDL,
    *consentimiento_buzones.DDL,
    """
    CREATE TABLE IF NOT EXISTS exportacion_privacidad (
        id           uuid        PRIMARY KEY,
        usuario_id   uuid        NOT NULL,
        estado       text        NOT NULL,
        url_descarga text,
        firma        text,
        creado_en    timestamptz NOT NULL
    );
    CREATE INDEX IF NOT EXISTS exportacion_por_usuario ON exportacion_privacidad (usuario_id);
    -- El paquete firmado que descarga el titular (ADR-0030); se borra con la cuenta.
    ALTER TABLE exportacion_privacidad ADD COLUMN IF NOT EXISTS paquete jsonb;
    """,
)


class IdentityAccess:
    """Operaciones transaccionales y de bóveda de `identity-access`."""

    def __init__(
        self,
        configuracion: Configuracion | None = None,
        *,
        esquema: str = ESQUEMA,
        contratos: Contratos | None = None,
        kms: custodia_boveda.KmsLocal | None = None,
        proveedor_oidc: autenticacion_oidc.ProveedorOidc | None = None,
        consultor_designados: autenticacion_oidc.ConsultorDeDesignados | None = None,
        enviador_otp: autenticacion_oidc.EnviadorOtp | None = None,
        consultor_recursos: motor_autorizacion_abac.ConsultorDeRecursos | None = None,
        detector_anomalias: auditoria_y_revocacion.DetectorDeAnomalias | None = None,
        secreto_jwt: str | None = None,
        secreto_vale: str | None = None,
        reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        nuevo_id: Callable[[], UUID] = uuid4,
    ):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        semilla_kms = os.environ.get("TROTAMUNDOS_KMS_SECRETO")
        self._kms = kms or custodia_boveda.KmsLocal(
            hashlib.sha256(semilla_kms.encode("utf-8")).digest() if semilla_kms else None
        )
        self._proveedor_oidc = proveedor_oidc or autenticacion_oidc.ProveedorOidcSimulado(
            self._configuracion.region
        )
        self._consultor_designados = consultor_designados or autenticacion_oidc.ConsultorNulo()
        self._enviador_otp = enviador_otp or autenticacion_oidc.EnviadorOtpEnMemoria()
        self._consultor_recursos = (
            consultor_recursos or motor_autorizacion_abac.ConsultorDeRecursosNulo()
        )
        self._detector = detector_anomalias or auditoria_y_revocacion.DetectorDeAnomalias()
        self._secreto_jwt = (
            secreto_jwt or os.environ.get("TROTAMUNDOS_JWT_SECRETO") or secrets.token_hex(32)
        )
        self._secreto_vale = (
            secreto_vale or os.environ.get("TROTAMUNDOS_VALE_SECRETO") or secrets.token_hex(32)
        )
        self._reloj = reloj
        self._nuevo_id = nuevo_id

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)
        # Las versiones de KEK_region (vigente e inhabilitadas) sobreviven a un reinicio.
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            custodia_boveda.restaurar_kms(con, self._kms)

    # --- Sesiones ----------------------------------------------------------------------------

    def crear_sesion(self, cuerpo: Mapping[str, Any]) -> dict[str, Any]:
        error_auth: autenticacion_oidc.CredencialesInvalidas | None = None
        sesion: dict[str, Any] = {}
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            try:
                sesion = autenticacion_oidc.crear_sesion(
                    con,
                    self._proveedor_oidc,
                    codigo=str(cuerpo["codigo"]),
                    verificador_pkce=str(cuerpo["verificadorPkce"]),
                    uri_redireccion=str(cuerpo["uriRedireccion"]),
                    secreto_jwt=self._secreto_jwt,
                    ahora=self._reloj(),
                )
            except autenticacion_oidc.CredencialesInvalidas as exc:
                error_auth = exc
        if error_auth is not None:
            raise Problema(401, "No autenticado")
        return sesion

    def solicitar_codigo_invitado(self, cuerpo: Mapping[str, Any]) -> None:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            autenticacion_oidc.solicitar_codigo_invitado(
                con,
                self._consultor_designados,
                self._enviador_otp,
                comparticion_id=UUID(str(cuerpo["comparticionId"])),
                correo=str(cuerpo["correo"]),
                ahora=self._reloj(),
            )

    def verificar_codigo_invitado(self, cuerpo: Mapping[str, Any]) -> dict[str, Any]:
        denegado: autenticacion_oidc.AccesoInvitadoDenegado | None = None
        sesion: dict[str, Any] = {}
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            try:
                sesion = autenticacion_oidc.verificar_codigo_invitado(
                    con,
                    self._consultor_designados,
                    comparticion_id=UUID(str(cuerpo["comparticionId"])),
                    correo=str(cuerpo["correo"]),
                    codigo=str(cuerpo["codigo"]),
                    secreto_jwt=self._secreto_jwt,
                    ahora=self._reloj(),
                )
            except autenticacion_oidc.AccesoInvitadoDenegado as exc:
                denegado = exc
        if denegado is not None:
            raise no_encontrado()
        return sesion

    # --- Buzones -----------------------------------------------------------------------------

    def listar_buzones(self, usuario_id: UUID) -> list[dict[str, Any]]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            return consentimiento_buzones.listar_buzones(con, usuario_id)

    def conectar_buzon(
        self,
        usuario_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        huella = huella_de_solicitud(cuerpo)
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            bloquear_usuario(con, usuario_id)
            previa = respuesta_guardada(con, usuario_id, clave)
            if previa is not None:
                if previa.operacion != "POST /buzones" or previa.huella != huella:
                    raise Problema(400, "Idempotency-Key reutilizada con otra solicitud")
                return previa.estado, previa.cuerpo

            region = (
                autenticacion_oidc.obtener_region_usuario(con, usuario_id)
                or self._configuracion.region
            )
            try:
                respuesta, cambios = consentimiento_buzones.conectar_buzon(
                    con,
                    self._kms,
                    usuario_id=usuario_id,
                    region=region,
                    via=str(cuerpo["via"]),
                    proveedor=cuerpo.get("proveedor"),
                    credencial_delegada=cuerpo.get("credencialDelegada"),
                    buzon_id=self._nuevo_id(),
                    ahora=self._reloj(),
                )
            except consentimiento_buzones.SolicitudBuzonInvalida as exc:
                raise Problema(400, str(exc)) from exc

            eventos = [
                Evento.nuevo(
                    "EstadoDeBuzonCambiado",
                    cambio,
                    productor=PRODUCTOR,
                    usuario_id=str(usuario_id),
                    region=region,
                    traceparent=traceparent,
                )
                for cambio in cambios
            ]
            if eventos:
                publicacion.registrar(con, eventos, self._contratos)
            guardar_respuesta(
                con,
                usuario_id,
                clave,
                RespuestaGuardada("POST /buzones", huella, 201, respuesta),
            )
            return 201, respuesta

    def autorizar_buzon(
        self,
        usuario_id: UUID,
        buzon_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            bloquear_usuario(con, usuario_id)
            try:
                respuesta, cambios = consentimiento_buzones.autorizar_buzon_oauth(
                    con,
                    self._kms,
                    usuario_id=usuario_id,
                    buzon_id=buzon_id,
                    codigo=str(cuerpo["codigo"]),
                    direccion=cuerpo.get("direccion"),
                    ahora=self._reloj(),
                )
            except consentimiento_buzones.BuzonNoEncontrado as exc:
                raise no_encontrado() from exc
            except (consentimiento_buzones.ConflictoDeBuzon, custodia_boveda.ErrorDeBoveda) as exc:
                raise Problema(409, str(exc)) from exc
            except consentimiento_buzones.SolicitudBuzonInvalida as exc:
                raise Problema(400, str(exc)) from exc

            region = (
                autenticacion_oidc.obtener_region_usuario(con, usuario_id)
                or self._configuracion.region
            )
            eventos = [
                Evento.nuevo(
                    "EstadoDeBuzonCambiado",
                    cambio,
                    productor=PRODUCTOR,
                    usuario_id=str(usuario_id),
                    region=region,
                    traceparent=traceparent,
                )
                for cambio in cambios
            ]
            if eventos:
                publicacion.registrar(con, eventos, self._contratos)
            return respuesta

    def desconectar_buzon(
        self,
        usuario_id: UUID,
        buzon_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> None:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            bloquear_usuario(con, usuario_id)
            try:
                cambios = consentimiento_buzones.desconectar_buzon(
                    con, usuario_id=usuario_id, buzon_id=buzon_id, ahora=self._reloj()
                )
            except consentimiento_buzones.BuzonNoEncontrado as exc:
                raise no_encontrado() from exc

            region = (
                autenticacion_oidc.obtener_region_usuario(con, usuario_id)
                or self._configuracion.region
            )
            eventos = [
                Evento.nuevo(
                    "EstadoDeBuzonCambiado",
                    cambio,
                    productor=PRODUCTOR,
                    usuario_id=str(usuario_id),
                    region=region,
                    traceparent=traceparent,
                )
                for cambio in cambios
            ]
            if eventos:
                publicacion.registrar(con, eventos, self._contratos)

    def emitir_token_efimero(
        self,
        buzon_id: UUID,
        instancia_id: str,
        buckets_arrendados: set[int] | None,
    ) -> dict[str, Any]:
        bloqueada: consentimiento_buzones.InstanciaBloqueada | None = None
        token: dict[str, Any] = {}
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            try:
                token = consentimiento_buzones.emitir_token_efimero(
                    con,
                    self._kms,
                    self._detector,
                    buzon_id=buzon_id,
                    instancia_id=instancia_id,
                    buckets_arrendados=buckets_arrendados,
                    ahora=self._reloj(),
                )
            except consentimiento_buzones.InstanciaBloqueada as exc:
                # Deja confirmar el bloqueo y la auditoría en la base antes de responder 403.
                bloqueada = exc
            except consentimiento_buzones.BuzonNoEncontrado as exc:
                raise no_encontrado() from exc
            except (consentimiento_buzones.ConflictoDeBuzon, custodia_boveda.ErrorDeBoveda) as exc:
                raise Problema(409, str(exc)) from exc
        if bloqueada is not None:
            raise Problema(403, "Prohibido")
        return token

    # --- Autorización ABAC -------------------------------------------------------------------

    def evaluar_autorizacion(
        self, cuerpo: Mapping[str, Any], servicio_cliente: str
    ) -> dict[str, Any]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            return motor_autorizacion_abac.evaluar(
                con,
                self._consultor_recursos,
                sujeto=cuerpo["sujeto"],
                accion=str(cuerpo["accion"]),
                recurso=cuerpo["recurso"],
                secreto_vale=self._secreto_vale,
                actor_servicio=servicio_cliente,
                ahora=self._reloj(),
            )

    # --- Privacidad (ADR-0030) ---------------------------------------------------------------

    def listar_exportaciones(self, usuario_id: UUID) -> list[dict[str, Any]]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            filas = con.execute(
                """
                SELECT id, estado, url_descarga, firma
                FROM exportacion_privacidad
                WHERE usuario_id = %s
                ORDER BY creado_en DESC
                """,
                (usuario_id,),
            ).fetchall()
            salida = []
            for fila in filas:
                item: dict[str, Any] = {"id": str(fila["id"]), "estado": fila["estado"]}
                if fila["url_descarga"]:
                    item["urlDescarga"] = fila["url_descarga"]
                if fila["firma"]:
                    item["firma"] = fila["firma"]
                salida.append(item)
            return salida

    def pedir_exportacion(self, usuario_id: UUID, clave: UUID) -> tuple[int, dict[str, Any]]:
        huella = huella_de_solicitud({})
        instante = self._reloj().astimezone(timezone.utc)
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            bloquear_usuario(con, usuario_id)
            previa = respuesta_guardada(con, usuario_id, clave)
            if previa is not None:
                if previa.operacion != "POST /privacidad/exportaciones" or previa.huella != huella:
                    raise Problema(400, "Idempotency-Key reutilizada con otra solicitud")
                return previa.estado, previa.cuerpo

            eid = self._nuevo_id()
            paquete = {
                "usuarioId": str(usuario_id),
                "identidad": autenticacion_oidc.datos_de_identidad(con, usuario_id),
                "buzones": consentimiento_buzones.listar_buzones(con, usuario_id),
                "auditoria": auditoria_y_revocacion.historial_de_usuario(con, usuario_id),
            }
            firma = hashlib.sha256(
                json.dumps(paquete, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            url_descarga = f"https://privacidad.trotamundos.app/exportaciones/{eid}"
            con.execute(
                """
                INSERT INTO exportacion_privacidad (
                    id, usuario_id, estado, url_descarga, firma, creado_en, paquete
                ) VALUES (%s, %s, 'Lista', %s, %s, %s, %s)
                """,
                (eid, usuario_id, url_descarga, firma, instante, Jsonb(paquete)),
            )
            auditoria_y_revocacion.registrar_evento(
                con,
                usuario_id=usuario_id,
                actor=str(usuario_id),
                accion="exportar_datos_personales",
                recurso_tipo="privacidad",
                recurso_id=str(eid),
                resultado="permitido",
                ocurrido_en=instante,
            )
            respuesta = {
                "id": str(eid),
                "estado": "Lista",
                "urlDescarga": url_descarga,
                "firma": firma,
            }
            guardar_respuesta(
                con,
                usuario_id,
                clave,
                RespuestaGuardada("POST /privacidad/exportaciones", huella, 202, respuesta),
            )
            return 202, respuesta

    def suprimir_cuenta(
        self,
        usuario_id: UUID,
        clave: UUID,
        *,
        traceparent: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        huella = huella_de_solicitud({})
        instante = self._reloj().astimezone(timezone.utc)
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            bloquear_usuario(con, usuario_id)
            previa = respuesta_guardada(con, usuario_id, clave)
            if previa is not None:
                if previa.operacion != "DELETE /privacidad/cuenta" or previa.huella != huella:
                    raise Problema(400, "Idempotency-Key reutilizada con otra solicitud")
                return previa.estado, previa.cuerpo

            # Fase 1 (ADR-0030): destruye secretos y DEK_u, borra buzones e identidad R1, y emite
            # CuentaSuprimida sin usuarioId (SobreSinUsuario) para el plano analítico. Cada buzón
            # revocado se publica como en DELETE /buzones/{id}, para que mail-ingest deje de leerlo.
            region = (
                autenticacion_oidc.obtener_region_usuario(con, usuario_id)
                or self._configuracion.region
            )
            cambios = []
            for buzon in consentimiento_buzones.listar_buzones(con, usuario_id):
                cambios += consentimiento_buzones.desconectar_buzon(
                    con, usuario_id=usuario_id, buzon_id=UUID(buzon["id"]), ahora=instante
                )
            if cambios:
                publicacion.registrar(
                    con,
                    [
                        Evento.nuevo(
                            "EstadoDeBuzonCambiado",
                            cambio,
                            productor=PRODUCTOR,
                            usuario_id=str(usuario_id),
                            region=region,
                            traceparent=traceparent,
                        )
                        for cambio in cambios
                    ],
                    self._contratos,
                )
            con.execute("DELETE FROM buzon WHERE usuario_id = %s", (usuario_id,))
            con.execute("DELETE FROM exportacion_privacidad WHERE usuario_id = %s", (usuario_id,))
            custodia_boveda.destruir_dek(
                con, usuario_id=usuario_id, actor=str(usuario_id), ahora=instante
            )
            seudonimo = autenticacion_oidc.eliminar_identidad_usuario(
                con, usuario_id, ahora=instante
            )
            if seudonimo:
                evento = Evento.nuevo(
                    "CuentaSuprimida",
                    {
                        "seudonimoAnalitico": seudonimo,
                        "suprimidaEn": instante.isoformat(),
                    },
                    productor=PRODUCTOR,
                    usuario_id=None,
                    region=None,
                    traceparent=traceparent,
                )
                publicacion.registrar(con, [evento], self._contratos)

            respuesta = {
                "solicitudId": str(self._nuevo_id()),
                "plazoFase1": (instante + timedelta(hours=24)).isoformat(),
                "plazoFase2": (instante + timedelta(days=30)).isoformat(),
            }
            guardar_respuesta(
                con,
                usuario_id,
                clave,
                RespuestaGuardada("DELETE /privacidad/cuenta", huella, 202, respuesta),
            )
            return 202, respuesta

    # --- Operaciones de mantenimiento y emergencia (ADR-0029) --------------------------------

    def rotar_kek(self, region: str, *, actor: str = "rotador-kek") -> tuple[int, int]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            return custodia_boveda.rotar_kek(
                con, self._kms, region, actor=actor, ahora=self._reloj()
            )

    def revocar_region_en_bloque(
        self,
        region: str,
        version_kek: int,
        *,
        actor: str = "respuesta-incidentes",
    ) -> int:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            cambios = consentimiento_buzones.revocar_region_en_bloque(
                con,
                self._kms,
                region=region,
                version_kek=version_kek,
                actor=actor,
                ahora=self._reloj(),
            )
            eventos = [
                Evento.nuevo(
                    "EstadoDeBuzonCambiado",
                    cambio,
                    productor=PRODUCTOR,
                    usuario_id=str(uid),
                    region=region,
                )
                for uid, cambio in cambios
            ]
            if eventos:
                publicacion.registrar(con, eventos, self._contratos)
            return len(eventos)

    def verificar_integridad_auditoria(self) -> bool:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            return auditoria_y_revocacion.verificar_cadena(con)

    def purgar_vencidos(self) -> None:
        """Bandeja de entrada y claves de idempotencia vencidas (ADR-0014) y códigos de invitado
        que ya no se pueden canjear."""
        ahora = self._reloj()
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as con:
            purgar(con, ahora)
            con.execute("DELETE FROM codigo_invitado WHERE expira_en < %s", (ahora,))

    # --- API y broker (ADR-0012, ADR-0020) ---------------------------------------------------

    def app(self) -> FastAPI:
        """La API de `identity-access`. Al arrancar crea el esquema (y recupera las versiones de
        `KEK_region`), corre la purga cada `intervalo_tareas_s` (0 la apaga) y, con un broker
        configurado, publica la *outbox*."""
        intervalo = self._configuracion.intervalo_tareas_s

        @asynccontextmanager
        async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
            self.crear_esquema()
            tareas = [asyncio.create_task(self._bucle(intervalo))] if intervalo > 0 else []
            try:
                async with self.con_broker():
                    yield
            finally:
                for tarea in tareas:
                    tarea.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await tarea

        return api.crear_app(self, self._contratos, self._secreto_jwt, lifespan=ciclo_de_vida)

    def topicos(self) -> list[str]:
        """Los tópicos que publica: uno por evento y carril posible."""
        prefijo = self._configuracion.prefijo_topicos
        return [topico(self._contratos, tipo, carril, prefijo)
                for tipo in sorted(publicacion.PUBLICA)
                for carril in carriles_posibles(self._contratos, tipo)]

    def publicador(self) -> PublicadorDeOutbox:
        c = self._configuracion
        return PublicadorDeOutbox(c.dsn_postgres, self._esquema, c.broker, self._contratos,
                                  c.prefijo_topicos)

    @contextlib.asynccontextmanager
    async def con_broker(self) -> AsyncIterator[list[asyncio.Task]]:
        """Arranca el publicador de la *outbox* si hay broker y lo detiene al salir."""
        servidores = self._configuracion.broker
        if not servidores:
            yield []
            return
        await asegurar_topicos(servidores, self.topicos())
        publicador = self.publicador()
        await publicador.iniciar()
        detener = asyncio.Event()
        # Referencia propia: el bucle de eventos solo guarda referencias débiles a las tareas.
        publicando = asyncio.create_task(self._publicar_siempre(publicador, detener))
        try:
            yield [publicando]
        finally:
            detener.set()
            publicando.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await publicando
            await publicador.detener()

    async def _bucle(self, intervalo: float) -> None:
        while True:
            await asyncio.sleep(intervalo)
            try:
                await asyncio.to_thread(self.purgar_vencidos)
            except Exception:  # la purga sigue en la próxima vuelta
                _registro_de_errores.exception("Falló la purga de identity-access")

    async def _publicar_siempre(self, publicador: PublicadorDeOutbox,
                                detener: asyncio.Event) -> None:
        while not detener.is_set():
            try:
                if await publicador.publicar_pendientes() == 0:
                    await asyncio.sleep(PAUSA_DEL_PUBLICADOR_S)
            except Exception:  # el broker o la base no responden: se reintenta
                _registro_de_errores.exception("Falló la publicación de la outbox de identity-access")
                await asyncio.sleep(PAUSA_DEL_PUBLICADOR_S)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.identity_access.servicio:crear_app`."""
    return IdentityAccess().app()
