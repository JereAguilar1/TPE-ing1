"""Las firmas HMAC de los *webhooks* de correo y de proveedores (ADR-0035, `provider-sync-webhooks`).

Una cabecera `X-Firma` con caracteres no ASCII es una firma inválida: antes hacía fallar
`hmac.compare_digest` con `TypeError` y el pedido terminaba en `500` (lo encontraron las pruebas
de contrato del paso 17).
"""

import pytest

from trotamundos.servicios.mail_ingest import receptor
from trotamundos.servicios.provider_sync import receptor_de_notificaciones


@pytest.mark.parametrize("modulo", [receptor, receptor_de_notificaciones])
def test_firma_valida_invalida_y_no_ascii(modulo):
    cuerpo, secreto = b'{"a": 1}', "secreto-de-prueba"
    firma = modulo.firma(cuerpo, secreto)
    assert modulo.firma_valida(cuerpo, firma, secreto)
    assert modulo.firma_valida(cuerpo, f"  {firma} ", secreto)
    assert not modulo.firma_valida(cuerpo, firma[:-1] + "0", secreto)
    assert not modulo.firma_valida(cuerpo, "ñandú", secreto)
    assert not modulo.firma_valida(cuerpo, None, secreto)
