# 5. Matriz de trazabilidad: driver → decisión → vista

Esta matriz es el artefacto que hace verificable a
[QA-16](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-16--trazabilidad-de-una-decisión-al-código)
(«100 % de los drivers referenciados por al menos un ADR») y a CRN-07. Se recorre en los dos
sentidos: desde un driver, para saber qué decisión lo atiende; y desde un elemento del sistema,
para saber por qué existe.

**Estado al cierre de la iteración 4 (cierre de la 1ra entrega):** **58 de 58 drivers (100 %)** están
atendidos por decisiones arquitectónicas explícitas (**`53 🟩` completamente tratados + `5 🟨` cuyo
único tramo restante es la implementación o calibración del prototipo en la 2da entrega; `0 ⬜`**).
La sección de [huecos de trazabilidad](#huecos-de-trazabilidad) queda **vacía**.

---

## Driver → decisión

*(Nota: `D10`–`D17` refieren a las decisiones `ADR-0010`–`ADR-0017` documentadas en
[Iteración 2 — Paso 4](../02-proceso-add/iteracion-2/paso-4-alternativas.md)).*

### Requisitos funcionales

| Driver | ADR / decisión que lo atiende | Elemento responsable | Estado |
|---|---|---|---|
| RF-01 Conectar cuenta de correo | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0029](../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md), [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | `identity-access`, `mail-ingest` | 🟩 |
| RF-02 Obtener mensajes de viaje | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), `D14`, [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | `mail-ingest` | 🟩 |
| RF-03 Extraer y normalizar reservas | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D10`, `D15`, [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | `booking-extraction` | 🟩 |
| RF-04 Filtros y whitelists | `D15` ([iteración 2](../02-proceso-add/iteracion-2/README.md#54-mail-ingest)) | `mail-ingest` | 🟩 |
| RF-05 Sincronizar con proveedores | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D14`, [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | `provider-sync` | 🟩 |
| RF-06 Gestión manual de reservas | `D10`, `D13`, [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md), [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | `itinerary-escritura` | 🟩 |
| RF-07 Agrupar reservas en viajes | `D10` ([iteración 2](../02-proceso-add/iteracion-2/paso-4-alternativas.md)) *(umbrales heurísticos se calibran en prototipo)* | `itinerary-escritura` | 🟨 |
| RF-08 Ciclo de vida del viaje | `D10`, [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md), [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) | `itinerary-escritura`, `preferences` | 🟩 |
| RF-09 Visualizar el panel | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), `D12`, [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md), [0033](../03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) | `bff-web`, `bff-mobile`, `itinerary-lectura`, `app-*` | 🟩 |
| RF-10 Notificar actualizaciones | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) | `notification` | 🟩 |
| RF-11 Compartir con designados | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md), [0028](../03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md) | `sharing`, `identity-access` | 🟩 |
| RF-12 Derivar a la agencia | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md), [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) | `support-liaison` | 🟩 |
| RF-13 Publicar en redes sociales | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0028](../03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md) | `sharing` | 🟩 |
| RF-14 Consultas analíticas | [0003](../03-adr/ADR-0003-separacion-planos.md), `D16`, [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md), [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) | `event-pipeline`, `analytics-store` | 🟩 |
| RF-15 Preferencias del usuario | `D12`, [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0031](../03-adr/ADR-0031-residencia-de-datos-por-region.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) | `preferences` | 🟩 |

### Escenarios de atributos de calidad

| Driver | ADR que lo atiende | Vista / especificación donde se ve | Estado |
|---|---|---|---|
| QA-01 Propagación ≤ 5 min *(ASR-1)* | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), `D14`, [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md), [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | [C&C N1](../04-vistas/vista-cyc-nivel-1.md#camino-de-ingesta--sostiene-qa-01) · [Iteración 3 §5.9](../02-proceso-add/iteracion-3/README.md#2-presupuesto-de-frescura-qa-01-p95--300-s-desde-la-generación-en-la-fuente) | 🟩 |
| QA-02 Panel web ≤ 800 ms | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md), [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md), [0031](../03-adr/ADR-0031-residencia-de-datos-por-region.md) | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) · [Pruebas de carga (Escenario 1)](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-1--qa-02-carga-pico-sostenida-del-panel-web) | 🟩 |
| QA-03 FCP móvil ≤ 1,4 s | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md), [0033](../03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) | [Iteración 3 §5.2](../02-proceso-add/iteracion-3/README.md#desglose-del-arranque-en-frío-móvil-sin-caché-local-qa-03-p75--1400-ms-en-4g) | 🟩 |
| QA-04 Pico de disrupción *(ASR-2)* | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md), [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) · [Pruebas de carga (Escenario 2)](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-2--qa-04-pico-súbito-por-disrupción-masiva) | 🟩 |
| QA-05 Pérdida de una región *(ASR-3)* | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0008](../03-adr/ADR-0008-alcance-disponibilidad.md), [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md), [0031](../03-adr/ADR-0031-residencia-de-datos-por-region.md) | [Despliegue N2 §5](../04-vistas/vista-despliegue-nivel-2.md#5-recorrido-de-caída-regional-qa-05-con-r-1-y-r-4-cerrados) · [Seguridad y datos §2](../04-vistas/vista-seguridad-y-datos.md#2-residencia-normativa-por-región-y-cierre-gráfico-de-r-6-crn-15--adr-0031) *(cierra `R-1`, `R-4`, `R-6`)* | 🟩 |
| QA-06 Proveedor externo caído | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0008](../03-adr/ADR-0008-alcance-disponibilidad.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) | 🟩 |
| QA-07 Despliegue sin inactividad | [0022](../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | [Despliegue N2 §4](../04-vistas/vista-despliegue-nivel-2.md#4-políticas-de-autoescalado-y-entrega-progresiva) | 🟩 |
| QA-08 Crecimiento de la base | [0021](../03-adr/ADR-0021-estrategia-autoescalado.md), [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) | [Despliegue N2 §3 y §6](../04-vistas/vista-despliegue-nivel-2.md#6-evolución-por-etapas-sobre-la-misma-topología-d26--cierre-de-r-3) | 🟩 |
| QA-09 Aislar la analítica | [0003](../03-adr/ADR-0003-separacion-planos.md), `D16`, [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md), [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) · [Pruebas de carga (Escenario 3)](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-3--qa-09-aislamiento-frente-a-consultas-analíticas-pesadas) | 🟩 |
| QA-10 Proveedor de viaje nuevo | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D17`, [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | [Módulos adaptadores N2](../04-vistas/vista-modulos-adaptadores.md) · [Guía verificada (`34 h-p ≤ 40 h-p`)](../02-proceso-add/iteracion-4/guias-de-extension.md#2-guía-cómo-agregar-un-proveedor-de-viaje-nuevo-verificación-de-qa-10) | 🟩 |
| QA-11 Formato de correo desconocido *(ASR-4)* | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D15`, [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md), [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | [Módulos adaptadores N2](../04-vistas/vista-modulos-adaptadores.md) · [Iteración 4 §5.2](../02-proceso-add/iteracion-4/README.md#52-cierre-de-qa-11-r-2-y-tratamiento-de-buzones-sin-oauth-d35--con-08) | 🟩 |
| QA-12 Solo personas designadas | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0028](../03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md) | [Seguridad y datos §1](../04-vistas/vista-seguridad-y-datos.md) · [Módulos adaptadores N2](../04-vistas/vista-modulos-adaptadores.md) | 🟩 |
| QA-13 Custodia de tokens *(ASR-5)* | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md), [0029](../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md), [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | [Seguridad y datos §1](../04-vistas/vista-seguridad-y-datos.md#1-fronteras-de-confianza-custodia-criptográfica-y-puntos-de-auditoría-qa-12--qa-13) | 🟩 |
| QA-14 Auditoría de datos personales | [0028](../03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md), [0029](../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md), [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) | [Seguridad y datos §4 y §5](../04-vistas/vista-seguridad-y-datos.md#4-catálogo-de-datos-personales-con-10--qa-14) | 🟩 |
| QA-15 Nuevo medio de transporte | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D11`, [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | [Módulos adaptadores N2](../04-vistas/vista-modulos-adaptadores.md) · [Guía verificada con `tren` (`68 h-p ≤ 80 h-p`)](../02-proceso-add/iteracion-4/guias-de-extension.md#1-guía-cómo-agregar-un-nuevo-medio-de-transporte-verificación-de-qa-15-con-tren) | 🟩 |
| QA-16 Trazabilidad al código | [0009](../03-adr/ADR-0009-contratos-spec-driven.md), `D17` | esta matriz (`58/58 = 100 %` documental; código fuente en 2da entrega) | 🟨 |
| QA-17 Contexto de ubicación | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0033](../03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) | [Módulos adaptadores N2](../04-vistas/vista-modulos-adaptadores.md) · [Seguridad y datos §4](../04-vistas/vista-seguridad-y-datos.md#4-catálogo-de-datos-personales-con-10--qa-14) | 🟩 |
| QA-18 Región nueva | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md), [0031](../03-adr/ADR-0031-residencia-de-datos-por-region.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) | [Guía verificada (`112 h-p ≤ 120 h-p`)](../02-proceso-add/iteracion-4/guias-de-extension.md#3-guía-cómo-incorporar-una-región-geográfica-nueva-verificación-de-qa-18) | 🟩 |

### Restricciones

| Driver | ADR / mecanismo | Estado |
|---|---|---|
| CON-01 ADD con ≥ 4 iteraciones | [Plan de iteraciones](../00-gestion/plan-de-iteraciones.md) (**4 de 4 iteraciones completas**) | 🟩 |
| CON-02 ADRs en MADR | [Plantilla](../03-adr/plantilla-madr.md) y registro en [03-adr](../03-adr/README.md) (`ADR-0001` a `ADR-0035`) | 🟩 |
| CON-03 Wiki con evolución y labor | [Bitácora](../00-gestion/bitacora.md), [convenciones](../00-gestion/equipo.md#convenciones-de-trabajo) | 🟩 |
| CON-04 Spec-driven development | [0009](../03-adr/ADR-0009-contratos-spec-driven.md), `D17`, [0022](../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) *(implementación del prototipo en 2da entrega)* | 🟨 |
| CON-05 Acotar el prototipo | [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) (criterio de tajada vertical sobre los 5 ASRs; se ejecuta en 2da entrega) | 🟨 |
| CON-06 Alojar el módulo avanzado | [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) y [verificación en papel de Opción A y B](../02-proceso-add/iteracion-4/README.md#57-verificación-en-papel-del-punto-de-extensión-para-la-2da-entrega-d34--con-06-con-05) *(se elige e implementa en 2da entrega)* | 🟨 |
| CON-07 APIs estándar | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | 🟩 |
| CON-08 Autorización explícita del correo | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0029](../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md), [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | 🟩 |
| CON-09 Equipo de 4 | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md), [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) | 🟩 |
| CON-10 Normativa de datos personales | [0029](../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md), [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md), [0031](../03-adr/ADR-0031-residencia-de-datos-por-region.md), [0033](../03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) *(cierra `R-6`)* | 🟩 |

### Inquietudes arquitectónicas

| Driver | ADR / mecanismo | Estado |
|---|---|---|
| CRN-01 Estructura general | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) y toda la iteración 1 | 🟩 |
| CRN-02 Asignar trabajo a 4 personas | [Mapa de responsabilidad](../04-vistas/vista-modulos-nivel-1.md#mapa-de-responsabilidad-por-integrante), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md) | 🟩 |
| CRN-03 Presupuesto de error | [0008](../03-adr/ADR-0008-alcance-disponibilidad.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md), [catálogo de SLOs](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#catálogo-de-indicadores-y-objetivos-de-nivel-de-servicio-slis--slos) | 🟩 |
| CRN-04 Despliegue sin inactividad | [0022](../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | 🟩 |
| CRN-05 Secretos y tokens | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0029](../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md) | 🟩 |
| CRN-06 Pruebas y contratos | [0009](../03-adr/ADR-0009-contratos-spec-driven.md), `D17`, [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md), [pruebas de carga especificadas](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md) | 🟩 |
| CRN-07 Trazabilidad | [0009](../03-adr/ADR-0009-contratos-spec-driven.md) y esta matriz completa al 100 % | 🟩 |
| CRN-08 Costo de infraestructura | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md), [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) *(cierra `R-3`)* | 🟩 |
| CRN-09 Cuotas de terceros | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | 🟩 |
| CRN-10 Internacionalización | [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) | 🟩 |
| CRN-11 Conflictos entre fuentes | `D13`, [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) | 🟩 |
| CRN-12 Idempotencia de la ingesta | `D14`, [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) *(cierra `R-4`)* | 🟩 |
| CRN-13 Consistencia entre regiones activas | [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) *(cierra `R-1` y `R-4`)* | 🟩 |
| CRN-14 Versionado de contratos publicados | [0009](../03-adr/ADR-0009-contratos-spec-driven.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | 🟩 |
| CRN-15 Residencia de datos por región | [0031](../03-adr/ADR-0031-residencia-de-datos-por-region.md) *(cierra `R-6`)* | 🟩 |

---

## Decisión → drivers (sentido inverso)

| ADR / Decisión | Decisión | Drivers que atiende |
|---|---|---|
| [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) | Microservicios orientados a eventos, granularidad acotada | QA-04, QA-05, QA-09, QA-10, QA-15, RF-10, CON-09, CON-A4, CRN-01, CRN-02, CRN-08 |
| [0002](../03-adr/ADR-0002-despliegue-multirregion.md) | Activo-activo en tres regiones | QA-05, QA-02, QA-03, QA-18, CRN-08, CRN-13 |
| [0003](../03-adr/ADR-0003-separacion-planos.md) | Planos operacional y analítico separados | QA-09, QA-02, QA-04, RF-14, CRN-08 |
| [0004](../03-adr/ADR-0004-obtencion-de-correo.md) | *Push* con reconciliación escalonada | QA-01, QA-04, QA-11, RF-02, CRN-09, CRN-08 |
| [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md) | Un BFF por tipo de cliente | QA-02, QA-03, QA-17, RF-09, CON-09 |
| [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | Anticorrupción con adaptadores como complementos | QA-10, QA-11, QA-15, QA-06, RF-03, RF-05, CON-07, CON-04 |
| [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | OIDC, delegación OAuth, lista de designados | QA-12, QA-13, RF-01, RF-11, RF-13, CON-08, CRN-05 |
| [0008](../03-adr/ADR-0008-alcance-disponibilidad.md) | Alcance de la medición de disponibilidad | QA-05, QA-06, CRN-03 |
| [0009](../03-adr/ADR-0009-contratos-spec-driven.md) | Contratos como artefactos de primera clase | CON-04, CON-02, QA-16, QA-10, CRN-06, CRN-07, CRN-14 |
| `D10`–`D17` ([Iter. 2](../02-proceso-add/iteracion-2/paso-4-alternativas.md)) | Modelo canónico, tipos extensibles, persistencia híbrida, conflictos, idempotencia, confianza, estrella analítica y pruebas de contrato | RF-02…RF-09, RF-14, RF-15, QA-01, QA-02, QA-09, QA-10, QA-11, QA-15, QA-16, CON-04, CRN-06, CRN-11, CRN-12 |
| [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) | Región primaria por usuario + testigo transregional + fusión ante *failover* + lectura causal | QA-05, CRN-13, CRN-12, CRN-11, QA-02, RF-06, CON-10 |
| [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) | Caché multinivel acotada e instantánea/arranque móvil | QA-02, QA-03, QA-01, RF-09, RF-15, QA-13 |
| [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) | Plazo propagado, tres carriles de prioridad y tres modos de degradación | QA-04, QA-01, QA-02, QA-09, RF-10, RF-13 |
| [0021](../03-adr/ADR-0021-estrategia-autoescalado.md) | Autoescalado híbrido + separación operativa `itinerary-lectura` / `itinerary-escritura` | QA-04, QA-02, QA-08, CRN-08, CRN-02, CON-09 |
| [0022](../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) | Entrega progresiva canaria secuencial + reversión automática + *expand/contract* | QA-07, CRN-04, QA-05, CON-04 |
| [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md) | Particionamiento `hash(usuario_id)` en `64` *buckets*, división en línea y archivo frío | QA-08, QA-02, CRN-08, RF-08, RF-11 |
| [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | Mamparo, cortacircuitos `≤ 25 s`, `cola_pendientes` 24 h y gobierno de cuotas/IMAP | QA-06, CRN-09, QA-01, RF-02, RF-05, RF-12 |
| [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) | OpenTelemetry correlacionado, sondas sintéticas/RUM y alertas por *burn rate* | CRN-03, QA-05, QA-06, QA-07, QA-09, CON-09 |
| [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) | Modelo de costo mensual y evolución en 3 etapas sin rediseño | CRN-08, QA-05, QA-08, QA-09, RF-14, CON-09 |
| [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | Evolución compatible de contratos, cabeceras `Deprecation`/`Sunset`, `versionEsquema` y `SemVer` en complementos | CRN-14, QA-10, QA-15, QA-07, CRN-04, CON-04, CON-09 |
| [0028](../03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md) | Políticas ABAC con vales JWS, desafío OTP para designados sin cuenta y `ResumenPublicable` por lista blanca | QA-12, QA-14, RF-11, RF-13 |
| [0029](../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md) | Cifrado por sobres (`KEK_region` / `DEK_u`), mTLS exclusivo en `identity-access`, detección `≤ 5 min` y revocación `≤ 15 min` | QA-13, CRN-05, CON-08, QA-14, RF-01 |
| [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) | Bitácora encadenada (`≤ 72 h` acceso) y supresión en dos fases (`< 24 h` OLTP/claves + `≤ 25 d` Parquet) | QA-14, CON-10, QA-09, CRN-08, RF-08, RF-14 |
| [0031](../03-adr/ADR-0031-residencia-de-datos-por-region.md) | Tres clases de residencia (`R1`/`R2`/`R3`) y testigo transregional cifrado jurisdiccional (`R-6` cerrado) | CRN-15, CON-10, QA-18, QA-05, QA-02 |
| [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) | Dominio neutral al idioma, catálogos ICU en CDN y formateo CLDR con `UTC + IANA TZ` | QA-18, CRN-10, RF-15, RF-09, RF-10, QA-03 |
| [0033](../03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) | Evaluación espacial en el dispositivo móvil con geocodificación única y degradación automática sin GPS | QA-17, QA-03, CON-10, RF-09 |
| [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) | Punto de extensión del módulo avanzado nº 14 (Opción A y B) y criterio de recorte del prototipo por ASRs | CON-06, CON-05, CON-A4, QA-04, QA-15 |
| [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | Alias de reenvío verificado / credenciales delegadas sin OAuth y huella sin PII + alta asistida ante formato desconocido | CON-08, QA-11, QA-13, RF-01, RF-03, RF-06 |

---

## Elemento → por qué existe

Este es el recorrido que QA-16 mide: «¿por qué existe este elemento?», respondido en menos de 10
minutos.

| Elemento | Existe porque… | ADR |
|---|---|---|
| `edge` | El presupuesto de latencia asigna 120 ms a la red del cliente y sirve estáticos, descriptores y catálogos ICU sin exponer PII | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) |
| `api-gateway` | Autenticación JWT local, límite de tasa y estampado de `X-Deadline-Ms` antes de tocar el dominio | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) |
| `bff-web` / `bff-mobile` | Los presupuestos de QA-02 (`800 ms`) y QA-03 (`≤ 15 KB`, `1,4 s`), la lectura causal `X-Min-Version` y la composición del módulo avanzado exigen contratos a medida | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) |
| `app-web` / `app-movil` (`contexto-ubicacion`) | Presentación dirigida por descriptores, localización CLDR y evaluación local de geocercas sin enviar GPS al servidor | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md), [0033](../03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) |
| `itinerary` (`-lectura` / `-escritura`) | Dueño único del modelo canónico; se despliega en dos grupos independientes para aislar lectura e ingesta sin abrir otro microservicio (`R-5`) | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md) |
| `identity-access` | QA-13, QA-12 y QA-14 exigen aislar en un único elemento la custodia de sobres `DEK_u`/`KEK_region`, la autorización ABAC, el acceso OTP de invitados y la auditoría/revocación | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0028](../03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md), [0029](../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md), [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) |
| `mail-ingest` | E/S contra terceros con mamparo, reconciliación, gobierno de cuota y receptor de reenvío verificado para cuentas sin OAuth | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md), [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) |
| `booking-extraction` | Cómputo sin estado con complementos versionados, 3 bandas de confianza y huella estructural anónima sin persistir cuerpos | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md), [0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) |
| `provider-sync` | QA-10 y QA-06 exigen aislar cada proveedor con su adaptador `SemVer`, cortacircuitos y `cola_pendientes` | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) |
| `sharing` | Compartir con designados (caducidad 30 d, revocación `≤ 60 s`) y publicar en redes (`ResumenPublicable` por lista blanca) tienen modelos de confianza distintos | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0028](../03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md) |
| `notification` | QA-01, QA-04 y QA-18 exigen despacho prioritario (`P1`) independiente del panel con plantillas ICU localizadas | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) |
| `support-liaison` | RF-12 y Opción B requieren armar el caso con contexto del viaje, adaptadores de agencia y mamparo de 3 s | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md), [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) |
| `preferences` | RF-08, RF-12 y RF-15 necesitan configuración de idioma, huso horario, región y agencia cacheada regionalmente | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) |
| `event-pipeline` / `analytics-store` | QA-09 y QA-14 exigen aislamiento físico (`P3`), desidentificación hacia `Clase R3` y compactación quincenal de supresión | [0003](../03-adr/ADR-0003-separacion-planos.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md), [0030](../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) |
| `recommendation-engine` *(A)* o `virtual-assistant` *(B)* | CON-06 exige alojar el módulo avanzado de la 2da entrega como elemento autónomo nº 14 (`< 15`) sobre eventos y APIs existentes | [0034](../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) |
| `modelo-canonico`, `contratos` y `locales-icu` | QA-15, CON-04, CRN-14 y QA-18 exigen tipos puros, contratos versionados y traducciones desacopladas del código de negocio | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0009](../03-adr/ADR-0009-contratos-spec-driven.md), [0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md), [0032](../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) |

---

## Huecos de trazabilidad

Al cierre de la iteración 4 (**cierre de la 1ra entrega**), **no quedan drivers sin ADR asignado
(`0` huecos de trazabilidad; cobertura `58/58 = 100 %`)**, cumpliendo los criterios de salida 1 y 3
del [plan de la iteración 4](../02-proceso-add/iteracion-4-plan.md#criterios-de-salida--y-cierre-de-la-1ra-entrega).

| Driver | Iteración asignada | Estado |
|---|---|---|
| — *(ninguno: 58/58 drivers cubiertos)* | — | ✅ Completo |
