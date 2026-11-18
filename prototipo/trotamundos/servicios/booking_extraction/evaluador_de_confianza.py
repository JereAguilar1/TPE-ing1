"""Bandas por extractor y mínimo de campos obligatorios (ADR-0015)."""


def evaluar(confianza: dict, obligatorios: set[str], umbrales: dict,
            solo_confirmacion: bool = False) -> tuple[str, dict]:
    por_campo = confianza['porCampo']
    if not obligatorios or not obligatorios.issubset(por_campo):
        raise ValueError('Falta confianza de campos obligatorios')
    puntaje = min(por_campo[campo] for campo in obligatorios)
    banda = ('baja' if puntaje < umbrales['bajo'] else
             'alta' if puntaje >= umbrales['alto'] and not solo_confirmacion else 'media')
    return banda, {'global': puntaje, 'porCampo': dict(por_campo)}
