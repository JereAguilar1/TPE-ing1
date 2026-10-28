# Iteración 4 — Refinar para interoperabilidad, seguridad, evolucionabilidad y uso internacional

> **Estado:** 📋 Planificada · **Responsables de coordinación:** Juan Emilio Pardo (interoperabilidad
> y evolucionabilidad), Ivo Iriarte (seguridad y privacidad)

Es la última iteración de la 1ra entrega, y la que cierra los drivers que las anteriores
postergaron deliberadamente. También es donde se **verifica** que la arquitectura puede alojar el
módulo avanzado de la 2da entrega, que es un criterio de salida y no una aspiración.

## Paso 1 — Entradas

Todo lo anterior: la estructura general, las estructuras internas, los contratos, las tácticas de
rendimiento y disponibilidad, y los ADRs 0001 a 0026.

## Paso 2 — Objetivo de la iteración

> Refinar las estructuras para satisfacer los escenarios de interoperabilidad, seguridad y
> privacidad, evolucionabilidad e internacionalización, y verificar que la arquitectura resultante
> aloja el módulo avanzado de la 2da entrega sin cambios estructurales.

### Drivers que consume

| Driver | Estado | Qué debe lograr esta iteración |
|---|---|---|
| QA-10 | 🟩 | **Verificar** con un adaptador real que «0 elementos modificados» se cumple |
| QA-11 | 🟨 | Cerrar el flujo del formato desconocido hacia el usuario |
| QA-12 | 🟩 | **Verificar**; resolver el caso del designado sin cuenta |
| QA-13 | 🟨 | Detección de extracción masiva, revocación en bloque, rotación de claves |
| QA-14 | ⬜ | Registro de auditoría, inventario de datos personales, supresión en todos los almacenes |
| QA-15 | 🟨 | **Verificar** en papel con «tren»: ≤ 2 elementos tocados |
| QA-16 | 🟨 | Cerrar la matriz de trazabilidad; el tramo hacia el código queda para la 2da entrega |
| QA-17 | ⬜ | Uso del GPS y degradación con permiso denegado |
| QA-18 | ⬜ | Externalización de recursos de localización, formatos locales, residencia de datos |
| CON-10 | ⬜ | Cumplimiento del marco normativo por región |
| CRN-05 | 🟨 | Rotación de claves y detección de acceso anómalo |
| CRN-07 | 🟩 | **Verificar** la cadena completa de trazabilidad |
| CRN-10 | ⬜ | Internacionalización como propiedad estructural |
| CRN-14 | nuevo | Versionado y evolución de los contratos publicados |
| CRN-15 | nuevo | Residencia de datos: qué datos pueden salir de la región del usuario |
| CON-06 | 🟨 | **Verificar** el punto de extensión del módulo avanzado |

## Paso 3 — Elementos a refinar

| Elemento | Por qué |
|---|---|
| Capa de anticorrupción (`provider-sync`, `booking-extraction`) | Versionado del contrato de adaptador (CRN-14) y verificación de QA-10 y QA-15 |
| `identity-access` | Se descompone en autenticación, consentimiento y autorización; cifrado, rotación y auditoría |
| `sharing` | Diseño de las dos operaciones y del caso del designado sin cuenta |
| `analytics-store` | Supresión de datos personales en un almacén columnar (el problema que [ADR-0003](../03-adr/ADR-0003-separacion-planos.md) dejó abierto) |
| Capa de clientes | Localización y uso del GPS |

## Paso 4 — Conceptos de diseño a evaluar

| Decisión | Alternativas |
|---|---|
| Versionado de contratos (CRN-14) | Versión en la ruta · negociación de contenido · solo cambios compatibles con campos opcionales · versionado del esquema de eventos con registro |
| Modelo de autorización | Control de acceso por roles · por atributos · políticas declarativas evaluadas centralmente |
| Cifrado y custodia | Clave única por sistema · clave por usuario (facilita la supresión criptográfica) · clave por región (facilita la residencia) |
| Supresión de datos personales (QA-14) | Borrado físico · supresión criptográfica (destruir la clave del usuario) · seudonimización con tabla de reidentificación |
| Residencia de datos (CRN-15) | Todo el dato en la región del usuario · solo los datos personales en la región, y los agregados globales · por categoría de dato |
| Internacionalización (QA-18) | Recursos externalizados por idioma · negociación por preferencia del usuario · formatos locales delegados a la plataforma |
| Tratamiento de IMAP sin OAuth | Exigir OAuth y limitar la cobertura · tratamiento acotado documentado (asunto abierto de [ADR-0007](../03-adr/ADR-0007-identidad-y-comparticion.md)) |

## Paso 6 — Artefactos esperados

| Artefacto | Contenido |
|---|---|
| Vista de módulos del subsistema de adaptadores | Estructura interna y contrato versionado del complemento |
| Vista de seguridad y de datos | Fronteras de confianza, flujo de datos personales, ubicación de las claves, puntos de auditoría |
| Guía «cómo agregar un medio de transporte» | Procedimiento paso a paso, que es a la vez la verificación documental de QA-15 |
| Guía «cómo agregar un proveedor» | Ídem para QA-10 |
| Catálogo de datos personales | Qué dato personal vive en qué almacén, con su base legal y su política de retención (CON-10, QA-14) |
| Matriz de trazabilidad completa | Los 53 drivers con su ADR, su vista y su contrato |
| Verificación del punto de extensión | Diseño en papel de la Opción A **y** de la Opción B sobre la estructura existente, mostrando que ninguna requiere interfaces nuevas |

## ADRs previstos

| ADR | Tema | Driver principal |
|---|---|---|
| ADR-0027 | Versionado y evolución de los contratos publicados | CRN-14, QA-10 |
| ADR-0028 | Modelo de autorización y evaluación de políticas | QA-12, QA-14 |
| ADR-0029 | Cifrado, custodia y rotación de claves | QA-13, CRN-05 |
| ADR-0030 | Supresión de datos personales en los dos planos | QA-14, CON-10 |
| ADR-0031 | Residencia de datos por región | CRN-15, CON-10, QA-18 |
| ADR-0032 | Estrategia de internacionalización y localización | QA-18, CRN-10 |
| ADR-0033 | Uso de capacidades nativas del dispositivo y degradación | QA-17 |
| ADR-0034 | Punto de extensión para el módulo avanzado de la 2da entrega | CON-06 |
| ADR-0035 | Tratamiento de buzones sin autorización delegada | CON-08, QA-11 |

## Criterios de salida — y cierre de la 1ra entrega

1. **Ningún driver en ⬜.** Los 53 están en 🟨 o 🟩, y cada 🟨 tiene documentado qué falta y por qué
   se posterga a la 2da entrega.
2. **Los cinco ASRs en 🟩**, o con su limitación explícitamente documentada.
3. **La matriz de trazabilidad está completa:** 100 % de los drivers referenciados por al menos un
   ADR (es la medida de QA-16).
4. **CON-06 verificado:** existe el diseño en papel de las dos opciones de módulo avanzado sobre la
   estructura actual, y ninguna requiere una interfaz nueva.
5. **Los tres riesgos residuales de la iteración 1 están cerrados** o explícitamente trasladados a
   la 2da entrega con su mitigación.
6. **Revisión de consistencia entre vistas:** las [siete reglas](../04-vistas/README.md#reglas-de-consistencia-entre-vistas)
   se verifican y el resultado se registra.

## Transición a la 2da entrega

Al cerrar esta iteración, la 1ra entrega está completa y la 2da puede empezar con:

| Lo que recibe la 2da entrega | De dónde viene |
|---|---|
| La arquitectura documentada con 35 ADRs y las vistas de niveles 1 y 2 | Iteraciones 1 a 4 |
| Los contratos OpenAPI y AsyncAPI, listos para implementar contra ellos | [ADR-0009](../03-adr/ADR-0009-contratos-spec-driven.md) |
| El punto de extensión verificado para la Opción A o la Opción B | ADR-0034 |
| Los escenarios QA como especificaciones de prueba ejecutables | Iteración 3 |
| La decisión de qué camino construir en el prototipo, acotado por CON-05 | A tomar al inicio de la 2da entrega |

La decisión de **qué recortar** del prototipo (CON-05) es la primera de la 2da entrega, y el
criterio está dado: construir los caminos que demuestran los cinco ASRs, porque son los que
justifican la arquitectura.
