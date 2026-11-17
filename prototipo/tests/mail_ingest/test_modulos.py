"""Los módulos de `mail-ingest` que no necesitan base: filtros, normalizador, reconciliador y
receptor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from trotamundos.servicios.mail_ingest import filtros, normalizador, receptor, reconciliador


def test_un_patron_es_una_direccion_o_un_dominio():
    assert filtros.coincide("reservas@miagencia.com", "Reservas@MiAgencia.com")
    assert not filtros.coincide("reservas@miagencia.com", "otra@miagencia.com")
    assert filtros.coincide("*@miagencia.com", "cualquiera@miagencia.com")
    assert filtros.coincide("miagencia.com", "cualquiera@miagencia.com")
    assert not filtros.coincide("*@miagencia.com", "x@avisos.miagencia.com")  # sin subdominios


def test_bloqueados_ganan_a_permitidos_y_permitidos_al_catalogo():
    lista = filtros.Filtros(permitidos=("*@agencia.com",), bloqueados=("spam@agencia.com",))
    assert filtros.admite(lista, "reservas@agencia.com")
    assert not filtros.admite(lista, "spam@agencia.com")
    assert not filtros.admite(lista, "reservas@aerolinea.com")  # catálogo vacío
    assert filtros.admite(lista, "reservas@aerolinea.com", catalogo=("*@aerolinea.com",))
    assert not filtros.admite(filtros.Filtros(bloqueados=("*@aerolinea.com",)),
                              "reservas@aerolinea.com", catalogo=("*@aerolinea.com",))


def test_el_normalizador_toma_la_fecha_del_mensaje_si_no_hay_otra():
    crudo = (b"From: =?utf-8?q?Aerol=C3=ADneas?= <reservas@aerolinea.com>\r\n"
             b"Subject: =?utf-8?q?Confirmaci=C3=B3n?=\r\n"
             b"Date: Fri, 20 Nov 2026 09:00:00 -0300\r\n\r\nHola\r\n")
    mensaje = normalizador.normalizar(crudo)
    assert mensaje["remitente"] == "reservas@aerolinea.com"
    assert mensaje["asunto"] == "Confirmación"
    assert mensaje["recibidoEn"] == "2026-11-20T12:00:00Z"
    assert mensaje["cuerpoTexto"].strip() == "Hola"
    assert "destinatarios" not in mensaje and "cuerpoHtml" not in mensaje


def test_la_reconciliacion_tiene_un_turno_fijo_por_buzon():
    """ADR-0004, punto 3: escalonada y determinista, para que la carga sea plana."""
    intervalo = timedelta(hours=6)
    ahora = datetime(2026, 11, 20, 12, 34, 56, tzinfo=timezone.utc)
    buzon = uuid4()
    primera = reconciliador.proxima(buzon, intervalo, ahora)
    assert ahora < primera <= ahora + intervalo
    assert reconciliador.proxima(buzon, intervalo, primera) == primera + intervalo
    assert reconciliador.proxima(buzon, intervalo, ahora) == primera  # siempre el mismo turno
    turnos = {reconciliador.proxima(uuid4(), intervalo, ahora) for _ in range(50)}
    assert len(turnos) > 40  # buzones distintos, turnos repartidos


def test_la_firma_del_aviso_es_un_hmac_del_cuerpo():
    cuerpo = b'{"suscripcionId":"s-1"}'
    firma = receptor.firma(cuerpo, "secreto")
    assert receptor.firma_valida(cuerpo, firma, "secreto")
    assert not receptor.firma_valida(cuerpo + b" ", firma, "secreto")
    assert not receptor.firma_valida(cuerpo, firma, "otro")
    assert not receptor.firma_valida(cuerpo, None, "secreto")
