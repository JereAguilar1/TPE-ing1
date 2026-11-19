"""Módulo `registro-de-adaptadores` (vista de adaptadores §1; ADR-0006, ADR-0011, ADR-0017, ADR-0027).

Carga los complementos `adaptador-*` por configuración declarativa, verifica en el arranque que el
manifiesto cumpla `contratos/plugins/adaptador.yaml`, que `version` sea SemVer, que `apiContrato`
sea `1.x` y que sus `tiposDeSegmento` estén registrados. Toda salida del complemento se valida
contra el esquema canónico y contra el descriptor de cada tipo de segmento antes de cruzar al resto
del servicio (regla R3).
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import yaml

from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.modelo import Fuente, ObservacionCanonica
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.provider_sync.interfaz_de_adaptador import AdaptadorDeProveedor

_SEMVER = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
_PREFIJO_COMPLEMENTOS = "trotamundos.servicios.provider_sync.complementos."
_ARCHIVO_CATALOGO = Path(__file__).with_name("catalogo_adaptadores.yaml")
_CONTRATO = "plugins/adaptador.yaml"


def entradas_configuradas() -> list[dict[str, Any]]:
    datos = yaml.safe_load(_ARCHIVO_CATALOGO.read_text(encoding="utf-8"))
    return list(datos or [])


@dataclass(frozen=True)
class AdaptadorRegistrado:
    manifiesto: dict[str, Any]
    credencial: dict[str, str]
    emisores: tuple[str, ...]
    instancia: AdaptadorDeProveedor

    @property
    def id(self) -> str:
        return str(self.manifiesto["id"])

    @property
    def version(self) -> str:
        return str(self.manifiesto["version"])

    @property
    def capacidades(self) -> Mapping[str, Any]:
        return self.manifiesto["capacidades"]


class RegistroDeAdaptadores:
    """Catálogo de adaptadores cargados por configuración y verificador de sus salidas."""

    def __init__(self, contratos: Contratos | None = None, *,
                 entradas: Iterable[Mapping[str, Any]] | None = None):
        self.contratos = contratos or contratos_por_omision()
        self.tipos = RegistroDeTipos.desde_contratos(self.contratos)
        self._por_id: dict[str, AdaptadorRegistrado] = {}
        self._por_emisor: dict[str, list[str]] = {}

        lista_entradas = list(entradas) if entradas is not None else entradas_configuradas()
        for entrada in lista_entradas:
            self._registrar_entrada(entrada)

    def _registrar_entrada(self, entrada: Mapping[str, Any]) -> None:
        manifiesto = dict(entrada["manifiesto"])
        self.contratos.validar(f"{_CONTRATO}#/manifiesto", manifiesto)
        if not _SEMVER.fullmatch(str(manifiesto["version"])):
            raise ValueError("La versión del adaptador no es SemVer")
        adaptador_id = str(manifiesto["id"])
        if adaptador_id in self._por_id:
            raise ValueError(f"Adaptador duplicado: {adaptador_id}")
        for tipo in manifiesto["tiposDeSegmento"]:
            self.tipos.obtener(tipo)

        credencial = dict(entrada.get("credencial") or {"tipo": "apiKey", "valor": "local"})
        self.contratos.validar(f"{_CONTRATO}#/definiciones/Credencial", credencial)

        instancia = entrada.get("instancia")
        if instancia is None:
            modulo = str(entrada.get("modulo") or "")
            if not modulo.startswith(_PREFIJO_COMPLEMENTOS):
                raise ValueError("El adaptador debe vivir en complementos")
            instancia = importlib.import_module(modulo).crear_adaptador()

        emisores = tuple(str(e) for e in entrada.get("emisores") or ())
        registrado = AdaptadorRegistrado(
            manifiesto=manifiesto,
            credencial=credencial,
            emisores=emisores,
            instancia=instancia,
        )
        self._por_id[adaptador_id] = registrado
        for emisor in emisores:
            self._por_emisor.setdefault(emisor, []).append(adaptador_id)

    def ids(self) -> list[str]:
        return list(self._por_id)

    def existe(self, adaptador_id: str) -> bool:
        return adaptador_id in self._por_id

    def obtener(self, adaptador_id: str) -> AdaptadorRegistrado:
        if adaptador_id not in self._por_id:
            raise KeyError(f"No hay adaptador registrado con id {adaptador_id!r}")
        return self._por_id[adaptador_id]

    def adaptadores_con_sondeo(self) -> list[AdaptadorRegistrado]:
        return [a for a in self._por_id.values() if a.capacidades.get("sondeo")]

    def adaptadores_para_emisor(self, emisor: str) -> list[str]:
        return list(self._por_emisor.get(emisor, ()))

    def _validar_observacion(self, registrado: AdaptadorRegistrado,
                             observacion: Mapping[str, Any]) -> None:
        self.contratos.validar("openapi/comun.yaml#/components/schemas/ObservacionCanonica",
                               observacion)
        self.tipos.validar_observacion(observacion)
        canonica = ObservacionCanonica.desde_dict(observacion)
        if canonica.fuente != Fuente.PROVEEDOR:
            raise ErrorDeContrato(
                f"{_CONTRATO}#/reglas",
                ["Toda observación de un adaptador debe tener fuente 'proveedor'"],
            )
        tipos_declarados = set(registrado.manifiesto["tiposDeSegmento"])
        for seg in canonica.segmentos:
            if seg.tipo not in tipos_declarados:
                raise ErrorDeContrato(
                    f"{_CONTRATO}#/manifiesto/properties/tiposDeSegmento",
                    [f"El adaptador {registrado.id} produjo un segmento de tipo {seg.tipo!r} "
                     f"no declarado en su manifiesto"],
                )

    def _validar_cambio(self, registrado: AdaptadorRegistrado,
                        cambio: Mapping[str, Any]) -> None:
        if set(cambio.keys()) != {"referencia", "observacion"}:
            raise ErrorDeContrato(
                f"{_CONTRATO}#/definiciones/CambioObservado",
                ["CambioObservado solo puede contener 'referencia' y 'observacion' (regla R3)"],
            )
        self.contratos.validar(f"{_CONTRATO}#/definiciones/CambioObservado", cambio)
        self._validar_observacion(registrado, cambio["observacion"])

    # --- Operaciones envueltas con validación contractual --------------------------------

    def obtener_reserva(self, adaptador_id: str, referencia: str) -> dict[str, Any]:
        registrado = self.obtener(adaptador_id)
        entrada = {"credencial": registrado.credencial, "referencia": referencia}
        self.contratos.validar(f"{_CONTRATO}#/operaciones/obtenerReserva/entrada", entrada)
        observacion = registrado.instancia.obtener_reserva(registrado.credencial, referencia)
        self.contratos.validar(f"{_CONTRATO}#/operaciones/obtenerReserva/salida", observacion)
        self._validar_observacion(registrado, observacion)
        return observacion

    def traducir_notificacion(self, adaptador_id: str, cabeceras: Mapping[str, str],
                              cuerpo: Any) -> list[dict[str, Any]]:
        registrado = self.obtener(adaptador_id)
        entrada = {"cabeceras": dict(cabeceras), "cuerpo": cuerpo}
        self.contratos.validar(f"{_CONTRATO}#/operaciones/traducirNotificacion/entrada", entrada)
        cambios = registrado.instancia.traducir_notificacion(cabeceras, cuerpo)
        self.contratos.validar(f"{_CONTRATO}#/operaciones/traducirNotificacion/salida", cambios)
        for cambio in cambios:
            self._validar_cambio(registrado, cambio)
        return cambios

    def sondear(self, adaptador_id: str, desde: str) -> list[dict[str, Any]]:
        registrado = self.obtener(adaptador_id)
        entrada = {"credencial": registrado.credencial, "desde": desde}
        self.contratos.validar(f"{_CONTRATO}#/operaciones/sondear/entrada", entrada)
        cambios = registrado.instancia.sondear(registrado.credencial, desde)
        self.contratos.validar(f"{_CONTRATO}#/operaciones/sondear/salida", cambios)
        for cambio in cambios:
            self._validar_cambio(registrado, cambio)
        return cambios

    def detectar_disrupcion(self, adaptador_id: str,
                            cambio: Mapping[str, Any]) -> dict[str, Any] | None:
        registrado = self.obtener(adaptador_id)
        self.contratos.validar(f"{_CONTRATO}#/operaciones/detectarDisrupcion/entrada", cambio)
        self._validar_cambio(registrado, cambio)
        disrupcion = registrado.instancia.detectar_disrupcion(cambio)
        self.contratos.validar(f"{_CONTRATO}#/operaciones/detectarDisrupcion/salida", disrupcion)
        return disrupcion
