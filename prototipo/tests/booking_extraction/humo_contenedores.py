"""Recorrido con Compose arriba: reenvío HTTP → broker → extracción → panel.

Ejecutar desde prototipo: .venv/bin/python -m tests.booking_extraction.humo_contenedores
Crea un usuario y un buzón sintéticos únicos; no modifica datos existentes.
"""
import asyncio
import copy
import json
import time
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

import httpx
from aiokafka import AIOKafkaProducer

from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import contratos_por_omision
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar


def esperar(funcion, limite=45):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        resultado = funcion()
        if resultado:
            return resultado
        time.sleep(.2)
    raise AssertionError('El recorrido no terminó dentro del plazo')


def main():
    c, contratos = Configuracion.desde_entorno(), contratos_por_omision()
    usuario, buzon = str(uuid4()), str(uuid4())
    alias = f'viajes+{uuid4().hex}@ingesta.trotamundos.app'
    estado = Evento.nuevo('EstadoDeBuzonCambiado', {
        'buzonId': buzon, 'estadoAnterior': 'Solicitado', 'estadoNuevo': 'Activo',
        'motivo': 'otorgado', 'via': 'reenvio', 'aliasReenvio': alias,
        'correoDelTitular': 'reservas@aerolinea.example'},
        productor='identity-access', usuario_id=usuario, region='AM')
    estado.validar(contratos)

    async def activar():
        productor = AIOKafkaProducer(bootstrap_servers=c.broker)
        await productor.start()
        try:
            clave, valor, cabeceras = estado.a_kafka()
            await productor.send_and_wait(topico(contratos, estado.tipo, 'P2'), valor,
                                           key=clave, headers=cabeceras)
        finally:
            await productor.stop()

    asyncio.run(activar())

    def activo():
        with conectar(c.dsn_postgres, 'mail_ingest') as conn:
            return conn.execute('SELECT 1 FROM buzon_ingesta WHERE buzon_id=%s AND activo',
                                (buzon,)).fetchone()
    esperar(activo)
    corpus = json.loads((Path(__file__).parent / 'corpus/reserva_simulada.json').read_text())
    inicio = time.monotonic()
    with httpx.Client(timeout=10) as cliente:
        for indice, rotulo in enumerate(('Localizador', 'Localizador tentativo',
                                         'Localizador dudoso', 'desconocido')):
            datos = copy.deepcopy(corpus[indice]['mensaje'])
            cuerpo = datos['cuerpoTexto'].replace('Localizador:', rotulo + ':')
            if rotulo == 'desconocido':
                cuerpo = 'Plantilla inédita: contenido sintético privado'
            correo = EmailMessage()
            correo['From'] = datos['remitente']
            correo['To'] = alias
            correo['Subject'] = datos['asunto']
            correo['Date'] = 'Wed, 18 Nov 2026 10:00:00 +0000'
            correo['Message-ID'] = f'<{uuid4()}@prueba.example>'
            correo['Authentication-Results'] = 'ingesta.trotamundos.app; dkim=pass; spf=pass'
            correo.set_content(cuerpo)
            respuesta = cliente.post('http://localhost:18104/webhooks/correo/reenvio',
                headers={'X-Alias-Destino': alias, 'X-Servicio-Cliente': 'mta-entrante',
                         'Content-Type': 'message/rfc822'}, content=bytes(correo))
            assert respuesta.status_code == 202, respuesta.text
            # Reenvío repetido: no duplica ni la reserva ni el aviso.
            assert cliente.post('http://localhost:18104/webhooks/correo/reenvio',
                headers={'X-Alias-Destino': alias, 'X-Servicio-Cliente': 'mta-entrante',
                         'Content-Type': 'message/rfc822'}, content=bytes(correo)).status_code == 202

        def panel_listo():
            respuesta = cliente.get('http://localhost:18102/panel', headers={'X-Usuario-Id': usuario})
            respuesta.raise_for_status()
            p = respuesta.json()
            confirmadas = [r for v in p['viajesActivos'] for r in v['reservas']]
            if len(confirmadas) == 1 and len(p['porConfirmar']) == 1:
                assert confirmadas[0]['estado'] == 'Confirmada'
                assert p['porConfirmar'][0]['estado'] == 'PorConfirmar'
                return p
        esperar(panel_listo)

    def salidas_listas():
        with conectar(c.dsn_postgres, 'booking_extraction') as conn:
            filas = conn.execute('SELECT tipo,carga FROM bandeja_salida WHERE usuario_id=%s '
                                 'AND publicado_en IS NOT NULL', (usuario,)).fetchall()
        if len(filas) != 4:
            return False
        assert sorted(f['tipo'] for f in filas) == ['ExtraccionNoReconocida'] * 2 + ['ReservaExtraida'] * 2
        assert {f['carga']['motivo'] for f in filas if f['tipo']=='ExtraccionNoReconocida'} == {
            'bandaBaja', 'formatoDesconocido'}
        assert 'contenido sintético privado' not in json.dumps(filas)
        return True
    esperar(salidas_listas)
    segundos = time.monotonic() - inicio
    assert segundos < 300
    print(f'QA-01/QA-11 humo OK en {segundos:.2f}s: alta confirmada, media por confirmar, '
          f'baja y desconocida sin reserva; duplicados sin efecto. Usuario sintético: {usuario}')


if __name__ == '__main__':
    main()
