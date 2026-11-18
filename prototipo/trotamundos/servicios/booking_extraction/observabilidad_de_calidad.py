"""Métricas locales sin contenido y disyuntor por extractor (ADR-0015, ADR-0035)."""
import hashlib
import json
from collections import Counter, defaultdict, deque
from html.parser import HTMLParser

_ETIQUETAS = frozenset('html head body title div span p a table thead tbody tr td th ul ol li br hr '
                       'b i strong em h1 h2 h3 h4 h5 h6 img style meta link section article footer '
                       'header main aside address blockquote pre code'.split())
_CABECERAS = frozenset({'from', 'to', 'subject', 'date', 'message-id', 'mime-version',
                        'content-type', 'content-transfer-encoding'})


class _Esqueleto(HTMLParser):
    def __init__(self):
        super().__init__()
        self.partes = []

    def handle_starttag(self, tag, attrs):
        self.partes.append(('abre', tag if tag in _ETIQUETAS else 'otra'))

    def handle_endtag(self, tag):
        self.partes.append(('cierra', tag if tag in _ETIQUETAS else 'otra'))

    def handle_startendtag(self, tag, attrs):
        self.partes.append(('vacia', tag if tag in _ETIQUETAS else 'otra'))


def huella(mensaje: dict) -> str:
    html = _Esqueleto()
    html.feed(mensaje.get('cuerpoHtml', ''))
    estructura = {
        'partes': [tipo for campo, tipo in [('cuerpoTexto', 'text/plain'), ('cuerpoHtml', 'text/html')]
                   if campo in mensaje],
        'html': html.partes,
        'cabeceras': sorted({nombre.lower() if nombre.lower() in _CABECERAS else 'otra'
                             for nombre in mensaje.get('cabeceras', {})}),
        # Solo clases MIME conocidas, nunca nombre, referencia ni contenido del adjunto.
        'adjuntos': [a.get('tipoMedio') if a.get('tipoMedio') in
                     {'application/pdf', 'text/plain', 'text/html', 'image/png', 'image/jpeg'}
                     else 'otro' for a in mensaje.get('adjuntos', [])],
    }
    return hashlib.sha256(json.dumps(estructura, sort_keys=True).encode()).hexdigest()


class Calidad:
    def __init__(self, ventana=20, minimo=20, umbral_bajas=0.5):
        if not 1 <= minimo <= ventana or not 0 <= umbral_bajas <= 1:
            raise ValueError('Parámetros del disyuntor inválidos')
        self.ventana, self.minimo, self.umbral_bajas = ventana, minimo, umbral_bajas
        self.bandas = Counter()
        self.huellas = Counter()
        self._recientes = defaultdict(lambda: deque(maxlen=ventana))
        self._abiertos = set()

    def solo_confirmacion(self, extractor_id):
        return extractor_id in self._abiertos

    def registrar(self, extractor_id, banda):
        self.bandas[(extractor_id, banda)] += 1
        recientes = self._recientes[extractor_id]
        recientes.append(banda == 'baja')
        if len(recientes) >= self.minimo and sum(recientes) / len(recientes) > self.umbral_bajas:
            self._abiertos.add(extractor_id)

    def desconocido(self, mensaje):
        fingerprint = huella(mensaje)
        dominio = mensaje['remitente'].rpartition('@')[2].lower()
        self.huellas[(dominio, fingerprint)] += 1
        return fingerprint
