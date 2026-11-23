"""El elemento `api-gateway`: la puerta de entrada pública (`api-gateway.yaml`, ADR-0005, ADR-0020,
ADR-0025, ADR-0027).

Por cada petición, en este orden:

1. **Cola acotada:** con 50 peticiones en curso, `503` con `Retry-After` (ADR-0020).
2. **Ruta:** solo lo que publica el contrato (`rutas`); lo demás, `404`.
3. **Versión de representación:** `Accept: application/vnd.trotamundos.v{N}+json`; solo existe la
   `v1` (por omisión). Otra versión, `406` (ADR-0027).
4. **Sesión:** verifica el JWT OIDC salvo en las operaciones públicas del contrato (ADR-0007).
5. **Límite de tasa:** cubeta de fichas por usuario, o por dirección en las públicas (`cubeta`).
6. **Modo operativo:** apaga lo que el modo apaga (`503`) y fija `X-Deadline-Ms`: 800 ms en
   `Normal` y `PicoElevado`, 1.500 ms en `DisrupcionMasiva` (`modos`).
7. **Traza y modo:** propaga `traceparent` o crea uno (ADR-0025) y manda el modo en
   `X-Modo-Operativo` (el asistente lo usa para degradarse, ADR-0040 §6); devuelve los dos.
8. Reenvía al servicio con ese plazo como tiempo máximo: si no responde a tiempo, `503`.

Con más de una región configurada (`TROTAMUNDOS_URL_BFF_WEB_<REGIÓN>`, paso 16), lo que va a
`bff-web` sale hacia el de la región primaria del usuario, o hacia el de su región de respaldo si
la primaria cayó (`regiones`, ADR-0018, QA-05). Sin esas variables, todo va al único `bff-web`.

No tiene estado propio más allá de las cubetas, las medidas del modo y la salud de las regiones,
en memoria (una réplica).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.comun.errores import Problema, instalar_manejadores, no_encontrado
from trotamundos.comun.sesion import region_de_sesion, usuario_de_sesion
from trotamundos.servicios.api_gateway import cubeta, modos, regiones, rutas

MAXIMO_EN_CURSO = 50
PLAZO_MS = {modos.NORMAL: 800, modos.PICO_ELEVADO: 800, modos.DISRUPCION_MASIVA: 1500}
# Funciones que apaga cada modo (iteración 3 §5.3): las publicaciones en redes (RF-13).
APAGADAS = {
    modos.PICO_ELEVADO: [("POST", re.compile(r"^/viajes/[^/]+/publicaciones$"))],
    modos.DISRUPCION_MASIVA: [("POST", re.compile(r"^/viajes/[^/]+/publicaciones$"))],
}
SERVICIOS = {
    "bff-web": ("TROTAMUNDOS_URL_BFF_WEB", "http://localhost:18108"),
    "bff-mobile": ("TROTAMUNDOS_URL_BFF_MOBILE", "http://localhost:18115"),
    "identity-access": ("TROTAMUNDOS_URL_IDENTITY_ACCESS", "http://localhost:18103"),
    "support-liaison": ("TROTAMUNDOS_URL_SUPPORT_LIAISON", "http://localhost:18105"),
    "preferences": ("TROTAMUNDOS_URL_PREFERENCES", "http://localhost:18112"),
    "mail-ingest": ("TROTAMUNDOS_URL_MAIL_INGEST", "http://localhost:18104"),
    "sharing": ("TROTAMUNDOS_URL_SHARING", "http://localhost:18116"),
}
REGIONES = ("AM", "EU", "AP")  # ADR-0002
# El servicio que se despliega por región y entre cuyas réplicas se conmuta.
REGIONAL = "bff-web"
_VERSION = re.compile(r"application/vnd\.trotamundos\.v(\d+)\+json")
_TRAZA = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
_SALTO_A_SALTO = {"host", "content-length", "connection", "keep-alive", "transfer-encoding",
                  "te", "upgrade", "proxy-authorization", "proxy-authenticate", "trailer"}
_NO_DEVOLVER = _SALTO_A_SALTO | {"content-encoding"}


def _no_disponible(detalle: str, espera_s: int = 2) -> Problema:
    return Problema(503, "Servicio no disponible", detalle,
                    cabeceras={"Retry-After": str(espera_s)})


def _traza(recibida: str | None) -> str:
    if recibida and _TRAZA.match(recibida):
        return recibida
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


def _version_pedida(accept: str | None) -> int:
    versiones = [int(v) for v in _VERSION.findall(accept or "")]
    return versiones[0] if versiones else 1


class ApiGateway:
    def __init__(self, *, contratos: Contratos | None = None, secreto_jwt: str | None = None,
                 urls: dict[str, str] | None = None, umbrales: modos.Umbrales | None = None,
                 transporte: httpx.AsyncBaseTransport | None = None,
                 reloj: Callable[[], float] = time.monotonic,
                 region: str | None = None, regionales: dict[str, str] | None = None):
        self._contratos = contratos or contratos_por_omision()
        self._rutas = rutas.Rutas(self._contratos)
        self._secreto_jwt = (secreto_jwt or os.environ.get("TROTAMUNDOS_JWT_SECRETO")
                             or secrets.token_hex(32))
        self._urls = urls if urls is not None else {
            nombre: os.environ.get(variable, omision).rstrip("/")
            for nombre, (variable, omision) in SERVICIOS.items()}
        self.cubeta = cubeta.CubetaDeFichas()
        self.modos = modos.MaquinaDeModos(umbrales)
        self._transporte = transporte
        self._reloj = reloj
        self._en_curso = 0
        # Multirregión (paso 16): la URL de bff-web de cada región, incluida la propia.
        self._region = region or os.environ.get("TROTAMUNDOS_REGION", "AM")
        if regionales is None:
            regionales = {r: os.environ[f"TROTAMUNDOS_URL_BFF_WEB_{r}"].rstrip("/")
                          for r in REGIONES if os.environ.get(f"TROTAMUNDOS_URL_BFF_WEB_{r}")}
        self._regionales = ({self._region: self._urls.get(REGIONAL, ""), **regionales}
                            if regionales else {})
        self.salud = regiones.SaludDeRegiones(self._regionales)

    def app(self) -> FastAPI:
        @asynccontextmanager
        async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
            async with httpx.AsyncClient(transport=self._transporte) as cliente:
                app.state.http = cliente
                vigilancia = (asyncio.create_task(self._vigilar_regiones(cliente))
                              if self._regionales else None)
                yield
                if vigilancia is not None:
                    vigilancia.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await vigilancia

        app = FastAPI(title="api-gateway", openapi_url=None, docs_url=None, redoc_url=None,
                      lifespan=ciclo_de_vida)
        instalar_manejadores(app)

        @app.api_route("/{ruta:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        async def pasar(request: Request) -> Response:
            if self._en_curso >= MAXIMO_EN_CURSO:
                raise _no_disponible("Demasiadas peticiones en espera", 2)
            self._en_curso += 1
            inicio = self._reloj()
            try:
                return await self._pasar(request, app.state.http)
            finally:
                self._en_curso -= 1
                self.modos.registrar(self._reloj(), self._reloj() - inicio)

        return app

    async def _pasar(self, request: Request, http: httpx.AsyncClient) -> Response:
        ruta, metodo = request.url.path, request.method
        destino = self._rutas.destino(metodo, ruta,
                                      request.headers.get("X-Tipo-Cliente", rutas.WEB).lower())
        if destino is None:
            raise no_encontrado()
        if _version_pedida(request.headers.get("Accept")) != 1:
            raise Problema(406, "Versión no disponible",
                           "La única representación es application/vnd.trotamundos.v1+json")
        usuario = None
        if destino.publica:
            clave = f"ip:{request.client.host if request.client else '-'}"
        else:
            usuario = usuario_de_sesion(request.headers.get("Authorization"), self._secreto_jwt)
            clave = str(usuario)
        espera = self.cubeta.tomar(clave, self._reloj())
        if espera is not None:
            raise Problema(429, "Demasiadas peticiones",
                           "Se superó el límite de 60 peticiones por minuto",
                           cabeceras={"Retry-After": str(espera)})

        modo = self.modos.evaluar(self._reloj())
        if any(m == metodo and patron.match(ruta) for m, patron in APAGADAS.get(modo, [])):
            raise _no_disponible(f"Función apagada en el modo {modo}", 60)
        url = self._urls.get(destino.servicio)
        if destino.servicio == REGIONAL and self._regionales:
            primaria = (region_de_sesion(request.headers.get("Authorization"), self._secreto_jwt)
                        if usuario is not None else None)
            region = regiones.region_para(usuario, primaria, self.salud, self._region)
            url = self._regionales[region] if region is not None else None
        if not url:
            raise _no_disponible(f"{destino.servicio} no está disponible")

        plazo_ms = PLAZO_MS[modo]
        traza = _traza(request.headers.get("traceparent"))
        cabeceras = {k: v for k, v in request.headers.items() if k.lower() not in _SALTO_A_SALTO}
        cabeceras.update({"traceparent": traza, "X-Deadline-Ms": str(plazo_ms),
                          "X-Modo-Operativo": modo})
        try:
            respuesta = await http.request(metodo, f"{url}{ruta}", params=request.query_params,
                                           content=await request.body(), headers=cabeceras,
                                           timeout=plazo_ms / 1000)
        except httpx.TimeoutException as error:
            raise _no_disponible("Se agotó el plazo de la petición") from error
        except httpx.HTTPError as error:
            raise _no_disponible(f"{destino.servicio} no responde") from error
        devueltas = {k: v for k, v in respuesta.headers.items() if k.lower() not in _NO_DEVOLVER}
        devueltas["traceparent"] = traza
        devueltas["X-Modo-Operativo"] = modo
        return Response(respuesta.content, status_code=respuesta.status_code, headers=devueltas)

    async def comprobar_regiones(self, http: httpx.AsyncClient) -> None:
        """Una ronda de la comprobación de salud de cada región (su `bff-web`)."""
        for region, url in self._regionales.items():
            try:
                respuesta = await http.get(f"{url}/tipos-de-segmento", timeout=regiones.ESPERA_S)
                sana = respuesta.status_code < 500
            except httpx.HTTPError:
                sana = False
            self.salud.registrar(region, sana, self._reloj())

    async def _vigilar_regiones(self, http: httpx.AsyncClient) -> None:
        while True:
            await self.comprobar_regiones(http)
            await asyncio.sleep(regiones.INTERVALO_S)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.api_gateway.servicio:crear_app`."""
    return ApiGateway().app()

