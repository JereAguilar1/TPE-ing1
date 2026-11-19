"""El intérprete por reglas y los catálogos (ADR-0037). No usan base ni broker."""

from __future__ import annotations

import ast
import re
from datetime import date, time
from pathlib import Path

import pytest

from tests.virtual_assistant.datos import AHORA, HOTEL, TREN, VIAJE, VUELO, itinerario_inicial
from trotamundos.servicios.virtual_assistant import catalogo
from trotamundos.servicios.virtual_assistant.catalogo import Mensajes
from trotamundos.servicios.virtual_assistant.interprete import (
    ContextoDelViajero,
    InterpretePorReglas,
)

PAQUETE = Path(catalogo.__file__).resolve().parent


@pytest.fixture(scope="module")
def interprete() -> InterpretePorReglas:
    return InterpretePorReglas()


@pytest.fixture(scope="module")
def contexto() -> ContextoDelViajero:
    datos = itinerario_inicial()
    return ContextoDelViajero(ahora=AHORA, viajes=datos["viajes"],
                              reservas=datos["viajes"][0]["reservas"],
                              por_confirmar=datos["porConfirmar"])


@pytest.mark.parametrize("texto, intencion", [
    ("Hola", "saludo"),
    ("buenas tardes", "saludo"),
    ("¿Qué podés hacer?", "ayuda"),
    ("¿Cómo viene mi viaje?", "estadoDelViaje"),
    ("¿A qué hora sale mi vuelo?", "proximoTramo"),
    ("¿Qué pasa con mi vuelo?", "proximoTramo"),
    ("¿Cuál es mi próximo tramo?", "proximoTramo"),
    ("Me pasaron el vuelo AR1402 al sábado a las 18:30", "corregirHorario"),
    ("ahora sale a las 11", "corregirHorario"),
    ("¿Tengo reservas por confirmar?", "confirmarReserva"),
    ("descartá la reserva del tren", "confirmarReserva"),
    ("tengo un conflicto en el hotel", "resolverConflicto"),
    ("mantené el mío", "resolverConflicto"),
    ("quiero cancelar el vuelo", "cambioAnteProveedor"),
    ("necesito un reembolso", "cambioAnteProveedor"),
    ("quiero hablar con mi agencia", "pedirAgencia"),
    ("pasame con una persona", "pedirAgencia"),
    ("¿Se canceló mi vuelo?", "proximoTramo"),  # una consulta, no un pedido ante el proveedor
    ("se canceló mi vuelo, quiero un reembolso", "cambioAnteProveedor"),
    ("¿Mi agencia ya recibió el caso?", "ayuda"),  # el seguimiento del caso, no otra derivación
    ("quiero hablar con mi agencia sobre mi caso", "pedirAgencia"),
    ("Sí", "confirmacion"),
    ("dale!", "confirmacion"),
])
def test_cada_intencion_con_sus_frases(interprete, contexto, texto, intencion):
    resultado = interprete.interpretar(texto, contexto)
    assert resultado.intencion == intencion and resultado.confianza >= 0.6


@pytest.mark.parametrize("texto", ["asdf qwerty", "el perro de mi vecino ladra", "42"])
def test_una_frase_fuera_de_los_patrones_no_se_entiende(interprete, contexto, texto):
    resultado = interprete.interpretar(texto, contexto)
    assert (resultado.intencion, resultado.confianza) == ("noEntendido", 0.0)
    assert resultado.reserva_id is None


def test_un_patron_debil_queda_por_debajo_del_umbral(interprete, contexto):
    assert interprete.interpretar("viajes", contexto).confianza < 0.6


def test_la_reserva_por_su_codigo_o_el_proximo_tramo(interprete, contexto):
    por_codigo = interprete.interpretar("me pasaron el ar 1402 al sábado", contexto)
    assert (por_codigo.reserva_id, por_codigo.por_referencia) == (VUELO, True)
    hotel = interprete.interpretar("¿a qué hora entro al HTL778?", contexto)
    assert hotel.reserva_id == HOTEL
    sin_codigo = interprete.interpretar("¿a qué hora sale?", contexto)
    assert (sin_codigo.reserva_id, sin_codigo.por_referencia) == (VUELO, False)
    por_tipo = interprete.interpretar("¿cuándo es el hotel?", contexto)
    assert (por_tipo.reserva_id, por_tipo.tipo) == (HOTEL, "hotel")
    por_confirmar = interprete.interpretar("confirmá la reserva IRYO6020", contexto)
    assert (por_confirmar.reserva_id, por_confirmar.por_referencia) == (TREN, True)


def test_el_viaje_por_su_titulo(interprete, contexto):
    assert interprete.interpretar("¿cómo viene el viaje a madrid?", contexto).viaje_id == VIAJE


@pytest.mark.parametrize("texto, fecha, hora", [
    # un día de la semana, sobre un tramo, es el más cercano a su fecha (jueves 3/12; ADR-0038)
    ("me pasaron el AR1402 al sábado a las 18:30", date(2026, 12, 5), time(18, 30)),
    ("me pasaron el AR1402 al martes", date(2026, 12, 1), None),
    ("lo pasaron a mañana a las 9", date(2026, 11, 21), time(9, 0)),
    ("me lo cambiaron para pasado mañana a las 9 y media", date(2026, 11, 22), time(9, 30)),
    ("lo movieron al 5/12 a las 18 hs", date(2026, 12, 5), time(18, 0)),
    ("me lo pasaron al 5 de diciembre", date(2026, 12, 5), None),
    ("ahora sale a las 07.45", None, time(7, 45)),
    ("me lo pasaron al viernes", date(2026, 12, 4), None),
    ("me lo pasaron a las 9 de la mañana", None, time(9, 0)),  # «de la mañana» no es el día siguiente
    ("me lo pasaron a mañana a las 9 de la noche", date(2026, 11, 21), time(21, 0)),
    ("ahora sale a las 7 y media de la tarde", None, time(19, 30)),
    ("lo movieron al 3/12/202", date(2026, 12, 3), None),  # un año de 3 cifras no es un año
    ("lo movieron al 2/1", date(2027, 1, 2), None),  # sin año, la próxima vez que llega
])
def test_fechas_y_horas_relativas(interprete, contexto, texto, fecha, hora):
    resultado = interprete.interpretar(texto, contexto)
    assert (resultado.fecha, resultado.hora) == (fecha, hora)


def test_sin_tramo_un_dia_de_la_semana_es_el_proximo_despues_de_hoy(interprete):
    contexto = ContextoDelViajero(ahora=AHORA)  # viernes 20/11, sin reservas
    assert interprete.interpretar("me lo pasaron al viernes", contexto).fecha == date(2026, 11, 27)


def test_el_dia_mas_cercano_al_tramo_no_cae_antes_de_hoy(interprete):
    """El 2/12, «al lunes» para el vuelo del jueves 3/12 no es el 30/11 (ya pasó): es el 7/12."""
    datos = itinerario_inicial()
    contexto = ContextoDelViajero(ahora=AHORA.replace(month=12, day=2), viajes=datos["viajes"],
                                  reservas=datos["viajes"][0]["reservas"])
    assert interprete.interpretar("me pasaron el AR1402 al lunes", contexto).fecha == \
        date(2026, 12, 7)


@pytest.mark.parametrize("texto, nombrada", [
    ("me pasaron el ar-1402 al sábado", True),
    ("me pasaron el AR 1402 al sábado", True),
    ("me pasaron el AR14025 al sábado", False),  # otro código que empieza igual
    ("me pasaron el vuelo a las 12:30", False),  # un código corto no se busca
])
def test_el_codigo_se_busca_como_palabra_entera(interprete, texto, nombrada):
    datos = itinerario_inicial()
    datos["viajes"][0]["reservas"][1]["segmentos"][0]["referencia"] = "12"
    contexto = ContextoDelViajero(ahora=AHORA, viajes=datos["viajes"],
                                  reservas=datos["viajes"][0]["reservas"])
    resultado = interprete.interpretar(texto, contexto)
    assert resultado.por_referencia is nombrada
    assert resultado.reserva_id == VUELO  # nombrado, o el próximo tramo


def test_hoy_es_el_dia_en_la_zona_del_tramo(interprete):
    """A las 01:00 UTC del 21/11 todavía es 20/11 en Buenos Aires: «mañana» es el 21."""
    datos = itinerario_inicial()
    tarde = AHORA.replace(day=21, hour=1)
    contexto = ContextoDelViajero(ahora=tarde, viajes=datos["viajes"],
                                  reservas=datos["viajes"][0]["reservas"])
    assert interprete.interpretar("el AR1402 me lo pasaron a mañana", contexto).fecha == \
        date(2026, 11, 21)


@pytest.mark.parametrize("texto, entidad, valor", [
    ("quiero cancelar el vuelo", "motivo", "cancelacion"),
    ("me pueden reprogramar el hotel?", "motivo", "reprogramacion"),
    ("confirmá la reserva del tren", "decision", "confirmar"),
    ("descartala, no es mía", "decision", "descartar"),
    ("quiero confirmar la reserva del tren", "decision", "confirmar"),
    ("¿tengo reservas por confirmar?", "decision", None),
    ("mantené el mío en el conflicto", "eleccion", "mantenerFijado"),
    ("aceptá el del proveedor en el conflicto", "eleccion", "aceptarFuente"),
])
def test_entidades(interprete, contexto, texto, entidad, valor):
    assert interprete.interpretar(texto, contexto).entidades.get(entidad) == valor


def test_un_reclamo_sin_motivo_conocido_no_trae_motivo(interprete, contexto):
    resultado = interprete.interpretar("quiero hacer un reclamo", contexto)
    assert resultado.intencion == "cambioAnteProveedor" and "motivo" not in resultado.entidades


# --- catálogos ------------------------------------------------------------------------------

def test_los_mensajes_completan_marcadores_y_plurales():
    m = Mensajes()
    assert m.texto("estado_por_confirmar", cantidad=1) == "Además, tenés 1 reserva por confirmar."
    assert m.texto("estado_por_confirmar", cantidad=3) == "Además, tenés 3 reservas por confirmar."
    assert m.tipo("autobus") == "micro" and m.tipo("crucero") == "reserva"


def test_las_fechas_se_formatean_en_la_zona_del_lugar():
    m = Mensajes()
    from tests.virtual_assistant.datos import BAIRES, MADRID
    from datetime import datetime, timezone
    instante = datetime(2026, 12, 3, 13, tzinfo=timezone.utc)
    assert m.fecha_y_hora(instante, BAIRES) == "jueves 3/12 10:00"
    assert m.fecha_y_hora(instante, MADRID) == "jueves 3/12 14:00"


def _constantes(arbol: ast.AST) -> list[ast.Constant]:
    """Las constantes de texto que no son *docstrings*."""
    docstrings = {id(n.body[0].value) for n in ast.walk(arbol)
                  if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
                  and n.body and isinstance(n.body[0], ast.Expr)
                  and isinstance(n.body[0].value, ast.Constant)}
    return [n for n in ast.walk(arbol)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


@pytest.mark.parametrize("modulo", ["dialogo.py", "derivacion.py"])
def test_los_textos_para_el_viajero_salen_del_catalogo(modulo):
    """Los módulos que le responden al viajero no tienen frases en el código (ADR-0037): una
    constante con tres palabras separadas por espacios sería un texto que no se puede traducir."""
    arbol = ast.parse((PAQUETE / modulo).read_text(encoding="utf-8"))
    frases = [n.value for n in _constantes(arbol)
              if len([p for p in n.value.split() if re.search(r"[a-záéíóúñ]{2,}", p, re.I)]) >= 3]
    assert frases == []


def test_cada_clave_usada_existe_en_el_catalogo():
    m = Mensajes()
    claves = set()
    for archivo in PAQUETE.glob("*.py"):
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr == "texto" and nodo.args
                    and isinstance(nodo.args[0], ast.Constant)):
                claves.add(nodo.args[0].value)
    faltan = sorted(c for c in claves if not m.tiene(c))
    assert claves and faltan == []


def test_solo_el_interprete_usa_los_patrones():
    """Ningún módulo salvo `interprete` sabe cómo se interpreta un texto (ADR-0037)."""
    usan = sorted(a.name for a in PAQUETE.glob("*.py")
                  if a.name != "catalogo.py" and "patrones(" in a.read_text(encoding="utf-8"))
    assert usan == ["interprete.py"]
