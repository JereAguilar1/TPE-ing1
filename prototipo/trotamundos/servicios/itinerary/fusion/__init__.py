"""Módulo `fusion` de `itinerary` (vista de módulos N2, ADR-0013).

* `consolidacion`: precedencia por fuente, campos fijados y conflictos. La vista consolidada es
  una función determinista de las entradas del agregado `Reserva` (ADR-0010).
* `identidad`: resolución de identidad por identificadores múltiples, unificación y sugerencias
  de posibles duplicados (nunca fusiona por parecido).
"""
