---
estado: aceptado
fecha: 2026-10-29
decisores: Francisco Lozano, Ivo Iriarte
consultados: Juan Emilio Pardo, Jeremias Aguilar
informados: equipo completo
iteracion: 4
drivers: CRN-15, CON-10, QA-18, QA-05, QA-02
---

# ADR-0031: Residencia de datos en tres clases de sensibilidad y testigo transregional cifrado bajo custodia jurisdiccional

## Contexto y planteo del problema

La iteración 3 resolvió la consistencia multirregión ([ADR-0018](ADR-0018-consistencia-datos-multirregion.md))
asignando a cada cuenta una `región_primaria` y confirmando las escrituras manuales con `RPO = 0`
(`QA-05`) mediante un **registro testigo síncrono** y una réplica caliente en una `región_respaldo`.
Al mismo tiempo, el paso 7 de esa iteración dejó registrado el riesgo residual **`R-6`**: bajo el
**Reglamento (UE) 2016/679 (GDPR, Cap. V)**, la **Ley 25.326 (Art. 12)** o futuros mercados con
residencia estricta (`QA-18`), replicar datos personales identificables en texto claro hacia un centro
de datos fuera de la jurisdicción autorizada infringe `CON-10`; pero confinar el `100 %` del estado a
una sola región geográfica sin respaldo externo destruye `QA-05` cuando esa región completa cae.

Se necesita una arquitectura de residencia de datos (`CRN-15`) que cierre **`R-6`** sin degradar ni un
segundo los objetivos de disponibilidad (`QA-05`) y lectura global (`QA-02`).

## Drivers de decisión

* **CRN-15** — definir con precisión qué categorías de datos deben permanecer en la región del usuario
  y cuáles pueden cruzar fronteras regionales y bajo qué salvaguardas técnicas.
* **CON-10** — cumplimiento de GDPR (UE) y Ley 25.326 (Argentina) sobre localización y transferencia
  internacional de datos personales.
* **QA-05 ([ADR-0018](ADR-0018-consistencia-datos-multirregion.md))** — conservar `RPO = 0` en escrituras confirmadas y conmutación en `≤ 60 s` ante pérdida total de una región.
* **QA-02 / QA-18** — mantener lectura rápida cuando un viajero se desplaza a otro continente e
  incorporar nuevas regiones regulatorias sin tocar la lógica de negocio.

## Opciones consideradas

* **F1** — Confinar el `100 %` de los datos y réplicas de cada usuario exclusivamente dentro de su
  región primaria, eliminando el respaldo interregional.
* **F2** — Replicar todos los datos personales en texto claro entre las tres regiones apoyándose solo
  en cláusulas contractuales administrativas.
* **F3** — Clasificar los datos en tres clases de residencia (`R1`, `R2`, `R3`), confinar `R1` en la
  `región_primaria`, cifrar en origen el testigo y contingencia `R2` bajo clave custodiada en la
  jurisdicción primaria (*ciphertext-only witness*) y gobernar las reglas mediante una tabla
  declarativa `politica_residencia`.

## Resultado de la decisión

Se adopta **F3**, cerrando formalmente el riesgo **`R-6`**:

1. **Clasificación obligatoria en tres clases de residencia:**
   * **Clase R1 — Identidad directa y secretos críticos (residencia estricta local):** perfil de
     identidad (`nombre`, `email`, `documento`), credenciales delegadas de buzones/proveedores, sobres
     de claves `DEK_u` y `mapa_seudonimo_usuario`. **Viven única y exclusivamente en la
     `región_primaria` asignada a la jurisdicción del usuario** y jamás se replican a otra región.
   * **Clase R2 — Operación de itinerario y contingencia (`reserva`, `segmento`, `viaje`,
     `panel_usuario` y registro testigo `D18`):** su copia activa reside en la `región_primaria`. El
     **registro testigo transregional** y la réplica de contingencia en la `región_respaldo` reciben
     únicamente **bloques cifrados en origen con `DEK_u`** ([ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md)),
     cuya clave maestra `KEK_jurisdiccion` reside en HSM con redundancia dentro del marco jurisdiccional
     aprobado (p. ej., anillo KMS multi-sede dentro del Espacio Económico Europeo o país con decisión
     de adecuación como Argentina/UE). De este modo, el nodo testigo fuera de la región aporta
     durabilidad física inmediata (`RPO = 0`) **sin poseer capacidad criptográfica para leer texto
     plano en reposo** (*ciphertext-only witness*, medida suplementaria conforme a recomendaciones EDPB
     01/2020).
   * **Clase R3 — Analítica desidentificada y telemetría operativa:** eventos transformados por el
     colector regional de `event-pipeline` (con `seudonimo_analitico`, sin nombres, correos, PNR ni
     direcciones exactas) y métricas/trazas OpenTelemetry sin PII ([ADR-0025](ADR-0025-observabilidad-sli-slo-presupuesto-error.md)).
     Pueden consolidarse globalmente en `analytics-store`.
2. **Lectura legítima del viajero en tránsito intercontinental (`QA-02`).** Cuando el propio titular
   viaja físicamente fuera de su `región_primaria` y abre su panel, el BFF local sirve su proyección
   en caché efímera cifrada en memoria (`TTL ≤ 15 min` tras desconexión), amparada expresamente por la
   ejecución del contrato de viaje a solicitud del interesado (GDPR Art. 49.1.b / Ley 25.326 Art. 12)
   sin persistir identidad `Clase R1` en disco fuera de su jurisdicción.
3. **Gobierno declarativo por configuración (`QA-18`).** La asignación `pais_residencia →
   { region_primaria, region_respaldo_permitida, anillo_kms_jurisdiccional, plazo_supresion_dias }`
   vive en el catálogo declarativo `politica_residencia`, permitiendo sumar un país o región nueva sin
   modificar código de dominio.

### Consecuencias

* **Bueno,** porque cierra **`R-6`** reconciliando `QA-05` (`RPO = 0` y desvío `≤ 60 s`) con `CON-10`
  (GDPR / Ley 25.326) mediante garantías criptográficas verificables y no meras promesas operativas.
* **Bueno,** porque mantiene en `0` los cambios de lógica de negocio al abrir un mercado con requisitos
  regulatorios propios (`QA-18`).
* **Malo,** porque exige que los sobres `Clase R2` enviados al registro testigo se cifren antes de
  salir de `itinerary-escritura` (`< 1 ms` con `AES-256-GCM` acelerado por hardware, absorbido dentro
  del margen de comandos manuales).

### Confirmación

* **Auditoría automatizada de fronteras de datos:** prueba de integración que crea un usuario con
  jurisdicción `EU`, ejecuta ingesta y edición manual, e inspecciona el almacenamiento de la
  `región_respaldo` y `analytics-store` comprobando que (a) existen `0` filas `Clase R1` fuera de `EU`,
  (b) el registro testigo en respaldo contiene únicamente carga cifrada `AES-256-GCM` indescifrable sin
  el KMS jurisdiccional, y (c) `analytics-store` carece de correos, nombres y códigos PNR.

## Pros y contras de las opciones

### F1 — Confinamiento total en una única región sin respaldo externo

* Bueno, porque simplifica al máximo el análisis territorial.
* **Malo, porque ante la caída completa de esa región incumple `QA-05` (pérdida de disponibilidad y de
  escrituras recientes).**

### F2 — Replicación global en texto claro a las tres regiones

* Bueno, porque no agrega cifrado de aplicación en la replicación.
* **Malo, porque expone datos personales de millones de viajeros en jurisdicciones ajenas y bloquea la
  adopción en mercados regulados (`CON-10`, `QA-18`).**

### F3 — Tres clases de residencia (`R1`/`R2`/`R3`) + testigo cifrado jurisdiccional + política declarativa

* Bueno, porque preserva intactas la disponibilidad multirregión, la privacidad normativa y la
  extensibilidad regional.
* Malo, porque requiere administrar anillos KMS por jurisdicción regulatoria.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D31](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d31--residencia-de-datos-por-región-y-resolución-de-r-6-crn-15-con-10-qa-18)
* Diagrama de residencia y fronteras: [vista-seguridad-y-datos](../04-vistas/vista-seguridad-y-datos.md)
* Guía de alta de nueva región: [guias-de-extension.md §3](../02-proceso-add/iteracion-4/guias-de-extension.md#3-guía-cómo-incorporar-una-región-geográfica-nueva-verificación-de-qa-18)
* Relacionados: [ADR-0002](ADR-0002-despliegue-multirregion.md), [ADR-0018](ADR-0018-consistencia-datos-multirregion.md), [ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md), [ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md)
