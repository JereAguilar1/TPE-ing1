"""Adaptador NDC simulado para aerolínea (`adaptador-aerolinea-simulada`, ADR-0006, QA-10).

Traduce el modelo externo simulado de la aerolínea (en JSON o XML estilo IATA NDC) al modelo
canónico (`ObservacionCanonica`, `CambioObservado`, `Disrupcion`) sin que ningún tipo o campo del
proveedor cruce la frontera de anticorrupción (regla R3).
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from trotamundos.servicios.provider_sync.interfaz_de_adaptador import (
    CargaInvalida,
    CuotaExcedida,
    NoEncontrada,
    ProveedorNoDisponible,
)

_AEROPUERTOS: dict[str, tuple[str, str, str]] = {
    "EZE": ("Ministro Pistarini", "AR", "America/Argentina/Buenos_Aires"),
    "AEP": ("Aeroparque", "AR", "America/Argentina/Buenos_Aires"),
    "MDZ": ("El Plumerillo", "AR", "America/Argentina/Mendoza"),
    "BRC": ("Teniente Luis Candelaria", "AR", "America/Argentina/Salta"),
    "COR": ("Ingeniero Ambrosio Taravella", "AR", "America/Argentina/Cordoba"),
    "MAD": ("Adolfo Suárez Madrid-Barajas", "ES", "Europe/Madrid"),
}
# Coordenadas de cada aeropuerto: con ellas `itinerary` reconoce la misma ciudad que un hotel o un
# traslado de otra fuente, que no traen código IATA (criterio de «misma ciudad», iteración 2 §5.1).
_COORDENADAS: dict[str, tuple[float, float]] = {
    "EZE": (-34.8222, -58.5358), "AEP": (-34.5592, -58.4156), "MDZ": (-32.8317, -68.7929),
    "BRC": (-41.1512, -71.1578), "COR": (-31.3236, -64.2080), "MAD": (40.4983, -3.5676),
}

_ESTADOS_SEGMENTO = {"OK": "confirmado", "HK": "confirmado", "TK": "confirmado",
                     "UN": "cancelado", "HX": "cancelado", "XX": "cancelado"}


def _instante_utc(valor: Any) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise CargaInvalida("Instante ausente o inválido en la carga del proveedor")
    try:
        dt = datetime.fromisoformat(valor.strip())
    except ValueError as error:
        raise CargaInvalida(f"Fecha inválida del proveedor: {valor!r}") from error
    if dt.tzinfo is None:
        raise CargaInvalida("El instante del proveedor debe incluir zona horaria")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _extremo(codigo: Any, instante: Any) -> dict[str, Any]:
    if not isinstance(codigo, str) or codigo not in _AEROPUERTOS:
        raise CargaInvalida(f"Aeropuerto desconocido en carga NDC: {codigo!r}")
    nombre, pais, zona = _AEROPUERTOS[codigo]
    return {
        "instante": _instante_utc(instante),
        "precision": "instante",
        "zonaHoraria": zona,
        "lugar": {
            "nombre": nombre,
            "codigo": codigo,
            "esquemaDeCodigo": "IATA",
            "pais": pais,
            "zonaHoraria": zona,
            "coordenadas": dict(zip(("lat", "lon"), _COORDENADAS[codigo])),
        },
    }


def _extraer_etiqueta(bloque: str, etiqueta: str) -> str | None:
    coincidencia = re.search(rf"<{etiqueta}>([^<]*)</{etiqueta}>", bloque)
    return coincidencia.group(1).strip() if coincidencia else None


def _parsear_xml_ndc(cuerpo_xml: str) -> dict[str, Any]:
    """Convierte una notificación XML NDC sintética `<OrderChangeNotif>` al diccionario nativo."""
    texto = cuerpo_xml.strip()
    if not texto.startswith("<OrderChangeNotif>") or not texto.endswith("</OrderChangeNotif>"):
        raise CargaInvalida("El XML no es un OrderChangeNotif válido")
    notificacion_id = _extraer_etiqueta(texto, "NotificationID")
    emitido = _extraer_etiqueta(texto, "Timestamp")
    orden_id = _extraer_etiqueta(texto, "OrderID")
    aerolinea = _extraer_etiqueta(texto, "OwnerCode")
    estado_orden = _extraer_etiqueta(texto, "OrderStatus") or "ACTIVE"
    if not all([notificacion_id, emitido, orden_id, aerolinea]):
        raise CargaInvalida("Faltan campos obligatorios en OrderChangeNotif XML")

    tramos = []
    for bloque_tramo in re.findall(r"<FlightSegment>(.*?)</FlightSegment>", texto, flags=re.DOTALL):
        numero = _extraer_etiqueta(bloque_tramo, "FlightNumber")
        origen = _extraer_etiqueta(bloque_tramo, "DepartureAirport")
        salida = _extraer_etiqueta(bloque_tramo, "DepartureTime")
        destino = _extraer_etiqueta(bloque_tramo, "ArrivalAirport")
        llegada = _extraer_etiqueta(bloque_tramo, "ArrivalTime")
        estado = _extraer_etiqueta(bloque_tramo, "ActionCode") or "HK"
        tramo: dict[str, Any] = {
            "flightNumber": numero,
            "departure": {"airport": origen, "time": salida},
            "arrival": {"airport": destino, "time": llegada},
            "statusCode": estado,
        }
        for clave_xml, clave_json in (("Terminal", "terminal"), ("Gate", "gate"),
                                      ("Seat", "seat"), ("Cabin", "cabin")):
            valor = _extraer_etiqueta(bloque_tramo, clave_xml)
            if valor:
                tramo[clave_json] = valor
        tramos.append(tramo)

    if not tramos:
        raise CargaInvalida("OrderChangeNotif XML sin segmentos de vuelo")

    orden: dict[str, Any] = {
        "orderId": orden_id,
        "owner": aerolinea,
        "orderStatus": estado_orden,
        "flights": tramos,
    }
    resultado: dict[str, Any] = {
        "notificationId": notificacion_id,
        "timestamp": emitido,
        "orders": [orden],
    }
    bloque_disr = re.search(r"<Disruption>(.*?)</Disruption>", texto, flags=re.DOTALL)
    if bloque_disr:
        cuerpo_disr = bloque_disr.group(1)
        afectadas = [r.strip() for r in re.findall(r"<AffectedOrder>([^<]+)</AffectedOrder>", cuerpo_disr)]
        resultado["disruption"] = {
            "disruptionId": _extraer_etiqueta(cuerpo_disr, "DisruptionID") or f"disr-{notificacion_id}",
            "severity": _extraer_etiqueta(cuerpo_disr, "Severity") or "alta",
            "reason": _extraer_etiqueta(cuerpo_disr, "Reason") or "Disrupción informada por la aerolínea",
            "affectedOrders": afectadas or [orden_id],
        }
    return resultado


def _traducir_tramo(aerolinea: str, indice: int, tramo: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(tramo, Mapping):
        raise CargaInvalida("El segmento NDC debe ser un objeto")
    numero = str(tramo.get("flightNumber") or "").strip()
    if not re.fullmatch(r"[0-9]{1,4}", numero):
        raise CargaInvalida(f"Número de vuelo inválido: {numero!r}")
    salida = tramo.get("departure")
    llegada = tramo.get("arrival")
    if not isinstance(salida, Mapping) or not isinstance(llegada, Mapping):
        raise CargaInvalida("Faltan extremos de salida o llegada en el tramo NDC")

    codigo_estado = str(tramo.get("statusCode") or "HK").upper()
    if codigo_estado not in _ESTADOS_SEGMENTO:
        raise CargaInvalida(f"Código de estado NDC desconocido: {codigo_estado!r}")
    estado = _ESTADOS_SEGMENTO[codigo_estado]

    detalle: dict[str, Any] = {
        "aerolinea": aerolinea,
        "numeroDeVuelo": numero,
    }
    for campo_ndc, campo_canonico in (("terminal", "terminal"), ("gate", "puerta"),
                                      ("seat", "asiento"), ("cabin", "clase")):
        valor = tramo.get(campo_ndc)
        if isinstance(valor, str) and valor.strip():
            detalle[campo_canonico] = valor.strip()

    extremo_inicio = _extremo(salida.get("airport"), salida.get("time"))
    extremo_fin = _extremo(llegada.get("airport"), llegada.get("time"))
    if extremo_fin["instante"] <= extremo_inicio["instante"]:
        raise CargaInvalida("El instante de llegada debe ser posterior al de salida")

    return {
        "tipo": "vuelo",
        "versionTipo": 1,
        "orden": indice,
        "inicio": extremo_inicio,
        "fin": extremo_fin,
        "operador": str(tramo.get("operatorName") or aerolinea),
        "referencia": f"{aerolinea}{numero}",
        "estado": estado,
        "detalle": detalle,
    }


def _traducir_orden(orden: Mapping[str, Any], *, id_evento: str,
                    emitido: str) -> tuple[str, dict[str, Any]]:
    if not isinstance(orden, Mapping):
        raise CargaInvalida("Cada orden NDC debe ser un objeto")
    referencia = str(orden.get("orderId") or "").strip()
    aerolinea = str(orden.get("owner") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,8}", referencia):
        raise CargaInvalida(f"Referencia de orden NDC inválida: {referencia!r}")
    if not re.fullmatch(r"[A-Z0-9]{2}", aerolinea):
        raise CargaInvalida(f"Código de aerolínea NDC inválido: {aerolinea!r}")

    vuelos = orden.get("flights")
    if not isinstance(vuelos, list) or not vuelos:
        raise CargaInvalida("La orden NDC debe contener al menos un vuelo")

    segmentos = [_traducir_tramo(aerolinea, i, t) for i, t in enumerate(vuelos)]
    estado_orden = str(orden.get("orderStatus") or "ACTIVE").upper()
    cancelada = estado_orden == "CANCELLED" or all(s["estado"] == "cancelado" for s in segmentos)
    if cancelada:
        for seg in segmentos:
            seg["estado"] = "cancelado"

    observacion: dict[str, Any] = {
        "fuente": "proveedor",
        "idDeFuente": f"ndc:{aerolinea}:{referencia}:{id_evento}",
        "versionDeFuente": _instante_utc(emitido),
        "cancelada": cancelada,
        "identificadores": [{"emisor": f"aerolinea:{aerolinea}", "codigo": referencia}],
        "segmentos": segmentos,
    }
    return referencia, observacion


class AdaptadorAerolineaSimulada:
    """Complemento `adaptador-aerolinea-simulada` que implementa `AdaptadorDeProveedor` v1.0."""

    def __init__(self) -> None:
        self._ordenes: dict[str, dict[str, Any]] = {}
        self._cambios: list[tuple[str, dict[str, Any]]] = []
        self._disrupciones_por_fuente: dict[str, dict[str, Any]] = {}
        self._fallo_simulado: Exception | None = None

    def simular_fallo(self, error: Exception | None) -> None:
        """Permite inyectar `CuotaExcedida` o `ProveedorNoDisponible` en pruebas."""
        self._fallo_simulado = error

    def registrar_orden_nativa(self, orden: Mapping[str, Any], *,
                               emitido: str = "2026-11-18T10:00:00Z",
                               id_evento: str = "alta",
                               disrupcion: Mapping[str, Any] | None = None) -> None:
        """Registra una orden o cambio nativo en el proveedor simulado para `obtener_reserva` y `sondear`."""
        referencia, observacion = _traducir_orden(orden, id_evento=id_evento, emitido=emitido)
        self._ordenes[referencia] = copy.deepcopy(observacion)
        cambio = {"referencia": referencia, "observacion": copy.deepcopy(observacion)}
        self._cambios.append((observacion["versionDeFuente"], cambio))
        if disrupcion is not None:
            self._guardar_disrupcion(observacion["idDeFuente"], referencia, disrupcion)

    def _verificar_disponibilidad(self, credencial: Mapping[str, str]) -> None:
        if not isinstance(credencial, Mapping) or not credencial.get("valor"):
            raise ProveedorNoDisponible("Credencial del proveedor ausente")
        if self._fallo_simulado is not None:
            raise self._fallo_simulado

    def _guardar_disrupcion(self, id_de_fuente: str, referencia: str,
                            bruta: Mapping[str, Any]) -> None:
        disrupcion_id = str(bruta.get("disruptionId") or "").strip()
        severidad = str(bruta.get("severity") or "alta").strip().lower()
        descripcion = str(bruta.get("reason") or "").strip()
        if not disrupcion_id or severidad not in {"alta", "media", "baja"} or not descripcion:
            raise CargaInvalida("Datos de disrupción inválidos en la carga del proveedor")
        afectadas_brutas = bruta.get("affectedOrders") or [referencia]
        if not isinstance(afectadas_brutas, list) or not afectadas_brutas:
            raise CargaInvalida("La disrupción debe indicar las referencias afectadas")
        afectadas = [str(r).strip() for r in afectadas_brutas if str(r).strip()]
        if referencia not in afectadas:
            afectadas.insert(0, referencia)
        self._disrupciones_por_fuente[id_de_fuente] = {
            "id": disrupcion_id,
            "severidad": severidad,
            "descripcion": descripcion,
            "referenciasAfectadas": afectadas,
        }

    # --- Operaciones del contrato AdaptadorDeProveedor -----------------------------------

    def obtener_reserva(self, credencial: Mapping[str, str],
                        referencia: str) -> dict[str, Any]:
        self._verificar_disponibilidad(credencial)
        if referencia not in self._ordenes:
            raise NoEncontrada(f"La reserva {referencia!r} no existe en el proveedor")
        return copy.deepcopy(self._ordenes[referencia])

    def traducir_notificacion(self, cabeceras: Mapping[str, str],
                              cuerpo: Any) -> list[dict[str, Any]]:
        if isinstance(cuerpo, (bytes, bytearray)):
            try:
                cuerpo = cuerpo.decode("utf-8")
            except UnicodeDecodeError as error:
                raise CargaInvalida("El cuerpo no es UTF-8 válido") from error
        if isinstance(cuerpo, str):
            datos = _parsear_xml_ndc(cuerpo)
        elif isinstance(cuerpo, Mapping):
            datos = dict(cuerpo)
        else:
            raise CargaInvalida("Formato de notificación no soportado")

        notificacion_id = str(datos.get("notificationId") or "").strip()
        emitido = datos.get("timestamp")
        ordenes = datos.get("orders")
        if not notificacion_id or not isinstance(ordenes, list) or not ordenes:
            raise CargaInvalida("Faltan notificationId u orders en la notificación NDC")

        disrupcion_bruta = datos.get("disruption")
        if disrupcion_bruta is not None and not isinstance(disrupcion_bruta, Mapping):
            raise CargaInvalida("El bloque disruption debe ser un objeto")

        traducidas: list[tuple[str, dict[str, Any]]] = [
            _traducir_orden(orden, id_evento=notificacion_id, emitido=emitido)
            for orden in ordenes
        ]
        salida: list[dict[str, Any]] = []
        for referencia, observacion in traducidas:
            if disrupcion_bruta is not None:
                self._guardar_disrupcion(observacion["idDeFuente"], referencia, disrupcion_bruta)
            self._ordenes[referencia] = copy.deepcopy(observacion)
            salida.append({"referencia": referencia, "observacion": observacion})
        return salida

    def sondear(self, credencial: Mapping[str, str],
                desde: str) -> list[dict[str, Any]]:
        self._verificar_disponibilidad(credencial)
        instante_desde = _instante_utc(desde)
        return [
            copy.deepcopy(cambio)
            for emitido, cambio in self._cambios
            if emitido >= instante_desde
        ]

    def detectar_disrupcion(self, cambio: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(cambio, Mapping) or "observacion" not in cambio or "referencia" not in cambio:
            raise CargaInvalida("CambioObservado inválido para detectarDisrupcion")
        observacion = cambio["observacion"]
        referencia = str(cambio["referencia"])
        id_de_fuente = str(observacion.get("idDeFuente") or "")

        registrada = self._disrupciones_por_fuente.get(id_de_fuente)
        if registrada is not None:
            return copy.deepcopy(registrada)

        if observacion.get("cancelada") is True:
            segmentos = observacion.get("segmentos") or []
            vuelo = segmentos[0].get("referencia", referencia) if segmentos else referencia
            return {
                "id": f"disr-{id_de_fuente}",
                "severidad": "alta",
                "descripcion": f"Cancelación informada por el proveedor para {vuelo}",
                "referenciasAfectadas": [referencia],
            }
        return None


def crear_adaptador() -> AdaptadorAerolineaSimulada:
    return AdaptadorAerolineaSimulada()
