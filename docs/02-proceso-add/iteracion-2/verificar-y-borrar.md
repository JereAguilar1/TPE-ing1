Qué decidí
Decisiones D10 a D17: El número de cada una coincide con el de su ADR (D10 → ADR-0010). Siete son estructurales y D17, la de pruebas, es de proceso, como D8 y D9 en la iteración 1.

Alternativas: En varias decisiones elegí una combinación en vez de una sola alternativa, y lo justifico en el paso 4:

D13: Identificadores múltiples, precedencia por fuente y coincidencia difusa solo como sugerencia.

D14: Clave de idempotencia por mensaje más fusión determinista. Descarté el registro de huellas porque no distingue un duplicado de un estado que vuelve a un valor anterior.

D15: Umbral por remitente con tres bandas.

Casos de uso: UC-1 a UC-7 quedan con recorrido paso a paso en el paso 7.

Kanban: Quedan 55 drivers, los 53 anteriores más CRN-11 y CRN-12. Ningún requisito funcional está en ⬜, hay 19 drivers en 🟩 y los números cierran con el kanban de la iteración 1.

Dos hallazgos que conviene que conozcan
Inconsistencia de la iteración 1: Su tabla de eventos hacía que notification consumiera ReservaActualizada publicada directamente por provider-sync, es decir, antes de fusionar. Lo corregí con un evento nuevo, ReservaObservada, y lo declaro en el paso 7 en «Ajustes a la iteración 1». Eso implica editar el README de la iteración 1, la vista C&C y el ADR-0006.

Defecto del modelo en la validación contra «tren»: Los boletos abiertos no tienen hora, así que agregué precision (instante o día). También dejo un matiz sobre QA-15: con los dos canales de datos (proveedor y correo) se tocan tres elementos, aunque el código existente modificado sigue siendo cero.

Qué tienen que revisar
Supuestos que inventé: La fecha (2026-10-28), los umbrales 0,90 / 0,60, los márgenes de 24 h y 72 h, la gracia de 3 días y la ventana de 14 días. Están marcados como supuestos a calibrar en la sección 5.11 del README.

Enlaces a páginas que todavía no existen: Los ocho ADRs (0010 a 0017), vista-modulos-nivel-2, secuencias-casos-primarios, el glosario ampliado y los contratos de contratos/. El paso 7 afirma que los criterios de salida se cumplen, así que esas piezas tienen que producirse y ser coherentes con lo escrito.

Dependencias con la iteración 3: R-1 y el nuevo R-4 comparten raíz, y CRN-12 no puede cerrarse antes de resolverlas.