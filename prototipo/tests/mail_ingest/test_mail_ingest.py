"""`mail-ingest` contra PostgreSQL (RF-02, RF-04, ADR-0004, CRN-12). Sin base, se saltean.

El proveedor de correo es el simulado de `complementos/`, y el token de `identity-access` lo da
un emisor de prueba que registra cada pedido.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.mail_ingest import descargador, reconciliador, suscripciones
from trotamundos.servicios.mail_ingest.servicio import MailIngest

USUARIO = UUID("00000000-0000-4000-8000-0000000000c1")
TITULAR = "viajero@test.app"
SECRETO_JWT = "secreto-jwt-de-prueba-de-32-bytes!"
AHORA = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


class EmisorDePrueba:
    """Hace de `identity-access`: entrega un token por pedido y recuerda cada uno."""

    def __init__(self) -> None:
        self.pedidos: list[str] = []
        self.no_disponibles: set[str] = set()
        self.fallan: set[str] = set()

    def token(self, buzon_id) -> str:
        buzon = str(buzon_id)
        self.pedidos.append(buzon)
        if buzon in self.fallan:
            raise RuntimeError("identity-access no responde")
        if buzon in self.no_disponibles:
            raise descargador.BuzonNoDisponible(buzon)
        return f"eph_{len(self.pedidos)}"


@pytest.fixture
def mail(dsn, esquema, contratos):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0)
    reloj = {"ahora": AHORA}
    servicio = MailIngest(configuracion, esquema=esquema, contratos=contratos,
                          emisor_de_tokens=EmisorDePrueba(), secreto_webhook="secreto-de-prueba",
                          secreto_jwt=SECRETO_JWT,
                          reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    servicio.bd, servicio.reloj, servicio.emisor = (dsn, esquema), reloj, servicio._emisor
    return servicio


def _filas(mail, consulta: str, *parametros) -> list[dict]:
    with conectar(*mail.bd) as conexion:
        return conexion.execute(consulta, parametros).fetchall()


def _estado(mail, buzon_id: UUID, nuevo: str, anterior: str = "Solicitado", **datos) -> None:
    carga = {"buzonId": str(buzon_id), "estadoAnterior": anterior, "estadoNuevo": nuevo,
             "motivo": "otorgado" if nuevo == "Activo" else "desconectadoPorUsuario", **datos}
    mail.consumir(Evento.nuevo("EstadoDeBuzonCambiado", carga, productor="identity-access",
                               usuario_id=str(USUARIO), region="AM"))


def _activar(mail, via: str = "oauth", **datos) -> UUID:
    buzon_id = uuid4()
    extra = {"proveedor": "gmail"} if via == "oauth" else {}
    _estado(mail, buzon_id, "Activo", via=via, correoDelTitular=TITULAR, **extra, **datos)
    return buzon_id


def _correo(remitente: str, asunto: str = "Tu reserva ABC123", cuerpo: str = "Vuelo AR1402",
            html: str | None = None) -> bytes:
    mensaje = EmailMessage()
    mensaje["From"] = f"Reservas <{remitente}>"
    mensaje["To"] = TITULAR
    mensaje["Subject"] = asunto
    mensaje["Date"] = "Fri, 20 Nov 2026 09:00:00 -0300"
    mensaje["Message-ID"] = f"<{uuid4()}@{remitente.partition('@')[2]}>"
    mensaje["Received"] = "from mx.ejemplo (10.0.0.1)"  # no tiene que pasar
    mensaje.set_content(cuerpo)
    if html:
        mensaje.add_alternative(html, subtype="html")
    return bytes(mensaje)


def _permitir(mail, *patrones: str, bloqueados: tuple[str, ...] = ()) -> None:
    mail.guardar_filtros(USUARIO, {"permitidos": list(patrones), "bloqueados": list(bloqueados)})


def _publicados(mail) -> list[dict]:
    return [f["carga"] for f in _filas(
        mail, "SELECT carga FROM bandeja_salida WHERE tipo = 'MensajeDeViajeRecibido' ORDER BY seq")]


def _avisar(cliente: TestClient, mail, suscripcion_id: str, firma: str | None = None):
    cuerpo = json.dumps({"suscripcionId": suscripcion_id, "historialDesde": "1"}).encode()
    return cliente.post("/webhooks/correo", content=cuerpo, headers={
        "X-Proveedor-Correo": "gmail", "Content-Type": "application/json",
        "X-Firma": firma if firma is not None else mail.firmar_aviso(cuerpo)})


# --- el camino completo -----------------------------------------------------------------------

def test_un_aviso_lleva_el_correo_permitido_hasta_la_outbox(mail):
    buzon_id = _activar(mail)
    proveedor = mail.adaptadores["oauth"]
    suscripcion = proveedor.suscripcion_de(str(buzon_id))
    assert suscripcion is not None
    mail.procesar_cola()  # la lectura inicial del alta: el buzón estaba vacío

    _permitir(mail, "*@aerolinea.com")
    proveedor.entregar(str(buzon_id), _correo("reservas@aerolinea.com", html="<p>Vuelo</p>"),
                       recibido_en=AHORA)
    cliente = TestClient(mail.app())
    assert _avisar(cliente, mail, suscripcion).status_code == 202
    assert mail.procesar_cola() == 1

    [publicado] = _publicados(mail)
    assert publicado["buzonId"] == str(buzon_id) and publicado["via"] == "oauth"
    mensaje = publicado["mensaje"]
    assert mensaje["remitente"] == "reservas@aerolinea.com"
    assert mensaje["destinatarios"] == [TITULAR]
    assert mensaje["recibidoEn"] == "2026-11-20T12:00:00Z"
    assert mensaje["asunto"] == "Tu reserva ABC123"
    assert mensaje["cuerpoTexto"].strip() == "Vuelo AR1402"
    assert mensaje["cuerpoHtml"].strip() == "<p>Vuelo</p>"
    assert "Received" not in mensaje["cabeceras"] and "Message-ID" in mensaje["cabeceras"]
    # Cada lectura pidió su token efímero a identity-access y usó ese (ADR-0029).
    assert mail.emisor.pedidos == [str(buzon_id), str(buzon_id)]
    assert proveedor.tokens_usados[-1] == "eph_2"


def test_el_mismo_mensaje_por_aviso_y_por_reconciliacion_se_publica_una_vez(mail):
    """ADR-0004: dos caminos que convergen; la bandeja (buzón, idDeMensaje) evita el doble."""
    buzon_id = _activar(mail)
    _permitir(mail, "*@aerolinea.com")
    mail.adaptadores["oauth"].entregar(str(buzon_id), _correo("reservas@aerolinea.com"))
    mail.procesar_cola()
    assert len(_publicados(mail)) == 1

    # La reconciliación vuelve a leer el buzón desde el principio (un cursor perdido, por
    # ejemplo): el mensaje ya procesado no se baja ni se publica de nuevo.
    with conectar(*mail.bd) as conexion:
        suscripciones.guardar_cursor(conexion, buzon_id, None)
    mail.reloj["ahora"] = AHORA + timedelta(days=2)
    mail.tareas_periodicas()
    assert mail.procesar_cola() == 1
    assert len(_publicados(mail)) == 1


def test_los_filtros_deciden_antes_de_bajar_el_cuerpo(mail):
    """RF-04: bloqueados > permitidos > catálogo."""
    buzon_id = _activar(mail)
    proveedor = mail.adaptadores["oauth"]
    _permitir(mail, "*@miagencia.com", "reservas@aerolinea.com",
              bloqueados=("promos@miagencia.com",))
    for remitente in ("reservas@miagencia.com", "promos@miagencia.com",
                      "reservas@aerolinea.com", "ofertas@aerolinea.com", "amigo@otro.com"):
        proveedor.entregar(str(buzon_id), _correo(remitente))
    bajados = []
    descargar = proveedor.descargar
    proveedor.descargar = lambda b, t, m: bajados.append(m) or descargar(b, t, m)

    mail.procesar_cola()

    assert sorted(p["mensaje"]["remitente"] for p in _publicados(mail)) == [
        "reservas@aerolinea.com", "reservas@miagencia.com"]
    assert len(bajados) == 2  # los otros tres no se bajaron
    # Lo que no pasó queda registrado con su motivo: nada se descarta en silencio.
    assert len(_filas(mail, "SELECT 1 FROM mensaje_recibido WHERE descartado = 'filtrado'")) == 3


def test_el_receptor_rechaza_la_firma_invalida_y_no_revela_suscripciones(mail):
    buzon_id = _activar(mail)
    mail.procesar_cola()
    cliente = TestClient(mail.app())
    suscripcion = mail.adaptadores["oauth"].suscripcion_de(str(buzon_id))

    assert _avisar(cliente, mail, suscripcion, firma="0" * 64).status_code == 401
    assert _avisar(cliente, mail, suscripcion, firma="").status_code == 401
    # Una suscripción que no existe se acepta igual y no encola nada.
    assert _avisar(cliente, mail, "sus-inexistente").status_code == 202
    assert _filas(mail, "SELECT * FROM cola_buzones") == []
    respuesta = cliente.post("/webhooks/correo", content=b"no es json",
                             headers={"X-Proveedor-Correo": "gmail",
                                      "X-Firma": mail.firmar_aviso(b"no es json")})
    assert respuesta.status_code == 400


def test_un_buzon_revocado_deja_de_atenderse(mail):
    buzon_id = _activar(mail)
    proveedor = mail.adaptadores["oauth"]
    assert proveedor.suscripcion_de(str(buzon_id)) is not None

    _estado(mail, buzon_id, "Revocado", anterior="Activo")

    assert proveedor.suscripcion_de(str(buzon_id)) is None
    assert _filas(mail, "SELECT * FROM cola_buzones") == []  # la lectura del alta se cancela
    mail.reloj["ahora"] = AHORA + timedelta(days=30)
    mail.tareas_periodicas()
    assert mail.procesar_cola() == 0


def test_un_buzon_imap_se_atiende_solo_por_reconciliacion(mail):
    buzon_id = _activar(mail, via="imapDelegado")
    [fila] = _filas(mail, "SELECT * FROM buzon_ingesta")
    assert fila["soporta_push"] is False and fila["suscripcion_id"] is None
    assert AHORA < fila["proxima_reconciliacion"] <= AHORA + reconciliador.INTERVALO_SIN_PUSH
    mail.procesar_cola()

    _permitir(mail, "*@aerolinea.com")
    mail.adaptadores["imapDelegado"].entregar(str(buzon_id), _correo("reservas@aerolinea.com"))
    mail.reloj["ahora"] = fila["proxima_reconciliacion"]
    mail.tareas_periodicas()
    mail.procesar_cola()
    assert len(_publicados(mail)) == 1


def test_una_suscripcion_caida_fuerza_una_reconciliacion_y_se_rehace(mail):
    proveedor = mail.adaptadores["oauth"]
    proveedor.fallar_suscripciones()
    buzon_id = _activar(mail)
    [encolado] = _filas(mail, "SELECT origen FROM cola_buzones")
    assert encolado["origen"] == "suscripcionCaida"
    mail.procesar_cola()

    proveedor.fallar_suscripciones(False)
    mail.tareas_periodicas()
    assert proveedor.suscripcion_de(str(buzon_id)) is not None
    [encolado] = _filas(mail, "SELECT origen FROM cola_buzones")
    assert encolado["origen"] == "suscripcionCaida"  # lo perdido mientras tanto se busca


def test_la_suscripcion_se_renueva_antes_de_vencer(mail):
    buzon_id = _activar(mail)
    [antes] = _filas(mail, "SELECT suscripcion_id, suscripcion_expira_en FROM buzon_ingesta")
    mail.reloj["ahora"] = antes["suscripcion_expira_en"] - timedelta(hours=1)
    mail.tareas_periodicas()
    [despues] = _filas(mail, "SELECT suscripcion_id, suscripcion_expira_en FROM buzon_ingesta")
    assert despues["suscripcion_id"] == antes["suscripcion_id"]
    assert despues["suscripcion_expira_en"] > antes["suscripcion_expira_en"]
    assert mail.adaptadores["oauth"].suscripcion_de(str(buzon_id)) == antes["suscripcion_id"]


def test_un_buzon_que_falla_no_frena_la_cola(mail):
    _permitir(mail, "*@aerolinea.com")
    roto, sano = _activar(mail), _activar(mail)
    mail.emisor.fallan.add(str(roto))
    mail.adaptadores["oauth"].entregar(str(sano), _correo("reservas@aerolinea.com"))

    mail.procesar_cola()

    assert [p["buzonId"] for p in _publicados(mail)] == [str(sano)]
    assert [f["buzon_id"] for f in _filas(mail, "SELECT buzon_id FROM cola_buzones")] == [roto]


def test_un_buzon_que_falla_se_reintenta_con_espera_creciente(mail):
    """ADR-0024: `5 s × 2^n`. Un proveedor caído no recibe un reintento por vuelta."""
    roto = _activar(mail)
    mail.emisor.fallan.add(str(roto))
    mail.procesar_cola()
    mail.procesar_cola()  # todavía en espera: no se vuelve a intentar
    assert mail.emisor.pedidos.count(str(roto)) == 1

    mail.reloj["ahora"] = AHORA + timedelta(seconds=5)
    mail.procesar_cola()
    assert mail.emisor.pedidos.count(str(roto)) == 2
    [fila] = _filas(mail, "SELECT intentos, no_antes_de FROM cola_buzones")
    assert fila["intentos"] == 2
    assert fila["no_antes_de"] == AHORA + timedelta(seconds=5 + 10)

    mail.emisor.fallan.clear()
    mail.reloj["ahora"] = AHORA + timedelta(seconds=15)
    mail.procesar_cola()
    assert _filas(mail, "SELECT * FROM cola_buzones") == []


def test_un_aviso_que_llega_mientras_se_lee_el_buzon_no_se_pierde(mail):
    """El buzón sale de la cola antes de leerse: un aviso nuevo lo vuelve a encolar."""
    buzon_id = _activar(mail)
    mail.procesar_cola()
    _permitir(mail, "*@aerolinea.com")
    proveedor = mail.adaptadores["oauth"]
    suscripcion = proveedor.suscripcion_de(str(buzon_id))
    cliente = TestClient(mail.app())
    proveedor.entregar(str(buzon_id), _correo("reservas@aerolinea.com", asunto="primero"))
    _avisar(cliente, mail, suscripcion)
    leer = proveedor.novedades

    def novedades_con_un_aviso_en_el_medio(buzon, token, cursor):
        novedades = leer(buzon, token, cursor)
        proveedor.novedades = leer
        proveedor.entregar(str(buzon_id), _correo("reservas@aerolinea.com", asunto="segundo"))
        assert _avisar(cliente, mail, suscripcion).status_code == 202
        return novedades

    proveedor.novedades = novedades_con_un_aviso_en_el_medio
    mail.procesar_cola()
    assert [p["mensaje"]["asunto"] for p in _publicados(mail)] == ["primero"]
    mail.procesar_cola()  # la próxima vuelta lee lo que avisó el segundo aviso
    assert [p["mensaje"]["asunto"] for p in _publicados(mail)] == ["primero", "segundo"]


def test_un_mensaje_ilegible_no_traba_al_buzon(mail):
    buzon_id = _activar(mail)
    _permitir(mail, "*@aerolinea.com")
    proveedor = mail.adaptadores["oauth"]
    proveedor.entregar(str(buzon_id), b"From: reservas@aerolinea.com\r\nSubject: x\r\n"
                       b"Content-Type: text/plain; charset=x-inexistente\r\n\r\nhola\r\n")
    proveedor.entregar(str(buzon_id), _correo("reservas@aerolinea.com"))

    mail.procesar_cola()

    assert len(_publicados(mail)) == 1
    assert _filas(mail, "SELECT descartado FROM mensaje_recibido WHERE descartado IS NOT NULL"
                  ) == [{"descartado": "ilegible"}]
    assert _filas(mail, "SELECT * FROM cola_buzones") == []


def test_sin_token_el_buzon_no_se_lee(mail):
    """Si identity-access dice que ya no está Activo, no se lee: llegará su evento."""
    buzon_id = _activar(mail)
    mail.emisor.no_disponibles.add(str(buzon_id))
    mail.adaptadores["oauth"].entregar(str(buzon_id), _correo("reservas@aerolinea.com"))
    _permitir(mail, "*@aerolinea.com")
    assert mail.procesar_cola() == 1
    assert _publicados(mail) == [] and mail.adaptadores["oauth"].tokens_usados == []


def test_un_evento_repetido_no_produce_un_segundo_efecto(mail, contratos):
    buzon_id = uuid4()
    evento = Evento.nuevo("EstadoDeBuzonCambiado", {
        "buzonId": str(buzon_id), "estadoAnterior": "Solicitado", "estadoNuevo": "Activo",
        "motivo": "otorgado", "via": "oauth", "proveedor": "gmail", "correoDelTitular": TITULAR},
        productor="identity-access", usuario_id=str(USUARIO), region="AM")
    mail.consumir(evento)
    primera = mail.adaptadores["oauth"].suscripcion_de(str(buzon_id))
    mail.consumir(evento)
    assert mail.adaptadores["oauth"].suscripcion_de(str(buzon_id)) == primera


# --- reenvío verificado (ADR-0035) -----------------------------------------------------------

ALIAS = "viajes+k3y9Qz@ingesta.trotamundos.app"


def _reenviado(remitente: str = "reservas@aerolinea.com", reenvia: str = TITULAR,
               autenticacion: str = "ingesta.trotamundos.app; dkim=pass; spf=pass",
               message_id: str | None = None) -> bytes:
    mensaje = EmailMessage()
    mensaje["Return-Path"] = f"<{reenvia}>"
    mensaje["Authentication-Results"] = autenticacion
    mensaje["From"] = remitente
    mensaje["To"] = ALIAS
    mensaje["Subject"] = "Tu reserva ABC123"
    mensaje["Date"] = "Fri, 20 Nov 2026 09:00:00 -0300"
    mensaje["Message-ID"] = message_id or f"<{uuid4()}@aerolinea.com>"
    mensaje.set_content("Vuelo AR1402")
    return bytes(mensaje)


def _reenviar(cliente: TestClient, crudo: bytes, alias: str = ALIAS,
              servicio_cliente: str = "mta-entrante"):
    return cliente.post("/webhooks/correo/reenvio", content=crudo, headers={
        "Content-Type": "message/rfc822", "X-Alias-Destino": alias,
        "X-Servicio-Cliente": servicio_cliente})


def _rechazos(mail) -> list[str]:
    return [f["motivo"] for f in _filas(mail, "SELECT motivo FROM reenvio_rechazado ORDER BY id")]


def test_un_reenvio_autenticado_del_titular_se_publica(mail):
    _activar(mail, via="reenvio", aliasReenvio=ALIAS)
    [fila] = _filas(mail, "SELECT * FROM buzon_ingesta")
    # No se lee de ningún lado: ni suscripción, ni cola, ni reconciliación.
    assert fila["suscripcion_id"] is None and fila["proxima_reconciliacion"] is None
    assert _filas(mail, "SELECT * FROM cola_buzones") == []
    cliente = TestClient(mail.app())

    # Reenvío automático: el From es la aerolínea y el ARC sobrevive al reenvío. No hace falta
    # que el remitente esté permitido: reenviar ya es una elección del usuario.
    automatico = _reenviado(autenticacion="ingesta.trotamundos.app; dkim=pass; spf=fail; arc=pass")
    assert _reenviar(cliente, automatico).status_code == 202
    # Reenvío manual: el From es el propio titular.
    assert _reenviar(cliente, _reenviado(remitente=TITULAR)).status_code == 202

    publicados = _publicados(mail)
    assert [p["via"] for p in publicados] == ["reenvio", "reenvio"]
    assert [p["mensaje"]["remitente"] for p in publicados] == ["reservas@aerolinea.com", TITULAR]
    assert mail.emisor.pedidos == []  # no hubo nada que leer con token


def test_un_reenvio_que_no_se_autentica_se_descarta_y_se_audita(mail):
    _activar(mail, via="reenvio", aliasReenvio=ALIAS)
    cliente = TestClient(mail.app())

    assert _reenviar(cliente, _reenviado(), servicio_cliente="otro").status_code == 403
    assert _reenviar(cliente, _reenviado(), alias="viajes+otro@ingesta.trotamundos.app"
                     ).status_code == 403
    # La autenticación que escribió otro servidor no cuenta: cualquiera la puede poner.
    assert _reenviar(cliente, _reenviado(autenticacion="mx.ajeno; dkim=pass; spf=pass")
                     ).status_code == 403
    assert _reenviar(cliente, _reenviado(autenticacion="ingesta.trotamundos.app; dkim=fail; "
                                                       "spf=pass")).status_code == 403
    assert _reenviar(cliente, _reenviado(reenvia="otra@persona.com")).status_code == 403

    assert _publicados(mail) == []
    assert _rechazos(mail) == ["aliasDesconocido", "autenticacionFallida",
                               "autenticacionFallida", "remitenteNoAutorizado"]


def test_un_reenvio_de_un_remitente_bloqueado_no_se_publica(mail):
    _activar(mail, via="reenvio", aliasReenvio=ALIAS)
    _permitir(mail, bloqueados=("*@aerolinea.com",))
    respuesta = _reenviar(TestClient(mail.app()), _reenviado())
    assert respuesta.status_code == 202
    assert _publicados(mail) == []
    assert _filas(mail, "SELECT descartado FROM mensaje_recibido") == [{"descartado": "bloqueado"}]


def test_el_mismo_reenvio_entregado_dos_veces_se_publica_una_vez(mail):
    _activar(mail, via="reenvio", aliasReenvio=ALIAS)
    cliente = TestClient(mail.app())
    crudo = _reenviado(message_id="<igual@aerolinea.com>")
    assert _reenviar(cliente, crudo).status_code == 202
    assert _reenviar(cliente, crudo).status_code == 202
    assert len(_publicados(mail)) == 1


# --- API de filtros (RF-04, mail-ingest-filtros.yaml) ----------------------------------------

def _sesion(sub: str = str(USUARIO)) -> dict[str, str]:
    """Una sesión como la que emite identity-access (`HS256`, `TROTAMUNDOS_JWT_SECRETO`)."""
    token = jwt.encode({"sub": sub, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       SECRETO_JWT, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_el_usuario_administra_sus_filtros(mail, contratos):
    cliente = TestClient(mail.app())
    tipo = {"Content-Type": "application/vnd.trotamundos.v1+json"}

    vacio = cliente.get("/filtros-de-correo", headers=_sesion())
    assert vacio.status_code == 200
    assert vacio.headers["content-type"].startswith("application/vnd.trotamundos.v1+json")
    assert vacio.json() == {"permitidos": [], "bloqueados": []}

    guardado = cliente.put("/filtros-de-correo", headers={**_sesion(), **tipo}, content=json.dumps(
        {"permitidos": ["*@MiAgencia.com", "*@miagencia.com"], "bloqueados": ["spam@x.com"]}))
    assert guardado.status_code == 200
    assert guardado.json() == {"permitidos": ["*@miagencia.com"], "bloqueados": ["spam@x.com"]}
    contratos.validar("openapi/mail-ingest-filtros.yaml#/components/schemas/FiltrosDeCorreo",
                      guardado.json())
    assert cliente.get("/filtros-de-correo", headers=_sesion()).json() == guardado.json()
    assert cliente.get("/filtros-de-correo/catalogo", headers=_sesion()).json() == [
        {"patron": "reservas@aerolinea.example", "extractorId": "extractor-reserva-simulada"},
        {"patron": "boletos@ferrocarril.example", "extractorId": "extractor-boleto-tren-simulado"},
        {"patron": "reservas@hotel.example", "extractorId": "extractor-reserva-hotel-simulada"}]


def test_los_filtros_piden_sesion_y_un_cuerpo_valido(mail):
    cliente = TestClient(mail.app())
    tipo = {"Content-Type": "application/vnd.trotamundos.v1+json"}
    assert cliente.get("/filtros-de-correo").status_code == 401
    assert cliente.get("/filtros-de-correo", headers={"Authorization": "Bearer roto"}
                       ).status_code == 401
    # Un invitado (ADR-0028) no tiene filtros: no es un usuario con cuenta.
    assert cliente.get("/filtros-de-correo", headers=_sesion("invitado:alguien@x.com")
                       ).status_code == 401
    invalido = cliente.put("/filtros-de-correo", headers={**_sesion(), **tipo},
                           content=json.dumps({"permitidos": ["no es un patrón"], "bloqueados": []}))
    assert invalido.status_code == 400
    assert invalido.json()["errores"][0]["campo"] == "permitidos[0]"
    assert cliente.put("/filtros-de-correo", headers={**_sesion(), **tipo},
                       content=json.dumps({"permitidos": []})).status_code == 400


@pytest.mark.parametrize("bloqueado", [False, True])
def test_catalogo_del_extractor_permite_descarga_salvo_bloqueo(mail, bloqueado):
    buzon_id = _activar(mail)
    remitente = "reservas@aerolinea.example"
    if bloqueado:
        _permitir(mail, bloqueados=(remitente,))
    proveedor = mail.adaptadores["oauth"]
    proveedor.entregar(str(buzon_id), _correo(remitente))
    bajados = []
    descargar = proveedor.descargar
    proveedor.descargar = lambda b, t, m: bajados.append(m) or descargar(b, t, m)
    mail.procesar_cola()
    assert len(bajados) == (0 if bloqueado else 1)
    assert len(_publicados(mail)) == (0 if bloqueado else 1)
