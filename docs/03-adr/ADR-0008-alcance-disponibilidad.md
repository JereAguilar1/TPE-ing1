---
estado: aceptado
fecha: 2026-10-24
decisores: Francisco Lozano, Jeremias Aguilar
consultados: Juan Emilio Pardo, Ivo Iriarte
informados: equipo completo
iteracion: 1
drivers: QA-05, QA-06, CRN-03, AMB-02
---

# ADR-0008: Alcance y forma de medición del objetivo de disponibilidad

## Contexto y planteo del problema

El enunciado fija que el sistema «debe ser accesible en todo momento, tolerando un máximo de 5
minutos por mes de tiempo de inactividad no planificada».

Enunciado así, el objetivo **no es medible y, bajo una lectura, es imposible**. Faltan tres cosas:

1. **Qué funciones entran en la medición.** ¿Cuenta como inactividad que no se pueda compartir un
   itinerario? ¿Que no se pueda ejecutar una consulta analítica?
2. **Qué se considera inactividad cuando falla un tercero.** El sistema tiene 12 interfaces
   externas. Si la caída de una aerolínea contara como inactividad de Trotamundos, el objetivo
   sería **imposible por construcción**: ningún proveedor de correo ni de viaje ofrece un SLA
   compatible con el 99,9884 %, y con 12 integraciones la probabilidad de que todas estén sanas
   simultáneamente durante un mes es baja.
3. **Dónde y cómo se mide.** Un objetivo de disponibilidad medido desde dentro del centro de datos
   y uno medido desde el cliente dan números muy distintos.

Sin resolver esto, QA-05 y QA-06 no son verificables, y CRN-03 —gestionar el presupuesto de error—
no tiene sobre qué operar. Por eso esto es una decisión arquitectónica y no un detalle de
operación: **determina contra qué se diseña**.

## Drivers de decisión

* **QA-05** — pérdida de una región: ≤ 1,5 min de presupuesto mensual consumido.
* **QA-06** — indisponibilidad de un proveedor externo: 0 peticiones de lectura fallidas por esa
  causa.
* **CRN-03** — hay que poder saber cuánto presupuesto de error queda.
* **AMB-02** — la ambigüedad que esta decisión resuelve.

## Opciones consideradas

* **I1** — Medir la disponibilidad de todo el sistema, incluidas las integraciones con terceros.
* **I2** — Medir solo las funciones propias, tratando la falla de un tercero como degradación.
* **I3** — Medir por función, con un objetivo distinto para cada una.

## Resultado de la decisión

Se adopta **I2, con el reparto de I3 dentro de las funciones propias**:

### 1. Qué se mide: las funciones críticas del usuario

| Función | ¿Entra en el objetivo de 5 min/mes? | Motivo |
|---|---|---|
| Autenticarse | ✅ Sí | Sin esto no hay sistema |
| Consultar el panel de viajes | ✅ Sí | Es la función central (MN-1) |
| Ver el detalle de un viaje | ✅ Sí | Ídem |
| Alta, modificación y baja manual de reservas | ✅ Sí | Es la vía que no depende de terceros |
| Recibir notificaciones | ⚠️ Objetivo propio, más laxo | Depende de servicios de notificación externos (E-15) |
| Ingesta automática desde correo y proveedores | ❌ No | Depende de terceros; se mide como **frescura** (QA-01), no como disponibilidad |
| Compartir y publicar itinerarios | ❌ No | Función secundaria; es parte de lo degradable ante sobrecarga |
| Consultas analíticas | ❌ No | Es lo primero que se degrada (QA-04); tiene su propio objetivo en QA-09 |

### 2. La falla de un tercero es degradación, no inactividad

Cuando un proveedor externo no responde, el sistema **sigue disponible**: muestra el último dato
conocido con su marca de frescura, y la actualización se recupera cuando el proveedor vuelve.
Mientras las funciones críticas de la tabla sigan respondiendo, **no se consume presupuesto de
error**. Esto es lo que
[QA-06](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-06--indisponibilidad-de-un-proveedor-externo)
exige, y es lo que hace que el objetivo del enunciado sea alcanzable en lugar de aspiracional.

La contrapartida es honesta y hay que decirla: **el usuario puede ver un itinerario desactualizado
mientras el sistema se declara disponible.** Por eso la marca de frescura visible no es un detalle
de interfaz, es parte de la decisión: el sistema nunca presenta un dato viejo como si fuera
actual.

### 3. Dónde se mide

**Desde el cliente**, no desde dentro de la infraestructura: una petición se considera exitosa si
el cliente recibió una respuesta correcta dentro del objetivo de latencia de QA-02. Una respuesta
que tarda 30 segundos no es una respuesta exitosa, aunque el servidor diga que sí.

### 4. Reparto del presupuesto

| Plano | Presupuesto mensual | Escenario asociado |
|---|---|---|
| Borde, DNS y enrutamiento global | 1,0 min | — |
| Plano de aplicación | 2,0 min | QA-07 (despliegues) |
| Plano de datos | 2,0 min | QA-05 (pérdida de región, tope 1,5 min) |
| **Total** | **5,0 min** | 99,9884 % |

### 5. Consecuencia que no es negociable

Con 5 minutos al mes **no existe ventana de mantenimiento posible**. Toda operación de
mantenimiento —despliegue, migración de esquema, rotación de claves— debe hacerse sin inactividad.
Esto es CRN-04 y es un driver estructural, no una preferencia de operación.

### Consecuencias

* **Bueno,** porque convierte un objetivo no medible en tres objetivos verificables, con un
  presupuesto repartido que permite atribuir el consumo a un plano concreto.
* **Bueno,** porque hace alcanzable el objetivo del enunciado sin relajarlo: lo que se acota es el
  **alcance** de la medición, no el número.
* **Bueno,** porque la frontera entre «crítico» y «degradable» es la misma que QA-04 necesita para
  decidir qué sacrificar durante un pico. Una sola frontera sirve a dos drivers.
* **Malo,** porque introduce una asimetría que hay que comunicar con cuidado: el sistema puede
  estar «disponible» con datos de varias horas de antigüedad si un proveedor estuvo caído. La
  marca de frescura visible es la mitigación, y es obligatoria.
* **Malo,** porque medir desde el cliente exige instrumentación de usuario real, que es trabajo
  adicional y plantea sus propias cuestiones de privacidad (hay que medir sin identificar).
* **Neutro,** porque es una interpretación del enunciado y debería validarse con la cátedra. Queda
  registrada como tal en [AMB-02](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución).

### Confirmación

* **Definición de los indicadores:** cada función de la tabla tiene un indicador de nivel de
  servicio definido (proporción de peticiones exitosas dentro del objetivo de latencia) y un
  objetivo asociado, declarados como configuración versionada.
* **Tablero de presupuesto de error:** debe mostrar en todo momento cuánto presupuesto mensual
  queda consumido, desglosado por plano. Sin esto, CRN-03 no se cumple.
* **Verificación de la atribución:** ante un incidente simulado de un proveedor externo, el
  presupuesto de error **no** debe disminuir, y la marca de frescura **sí** debe reflejarlo.

## Pros y contras de las opciones

### I1 — Medir todo el sistema, incluidas las integraciones

* Bueno, porque es lo que el usuario percibe: si su itinerario no se actualiza, al usuario le da
  igual de quién es la culpa.
* Bueno, porque es la lectura más literal del enunciado.
* **Malo, porque vuelve el objetivo imposible por construcción.** Con 12 integraciones externas, el
  99,9884 % conjunto exigiría de cada tercero una disponibilidad mayor que la que ofrece.
* Malo, porque haría que el equipo persiga un objetivo que no puede alcanzar, lo que en la práctica
  significa dejar de usar el objetivo como guía de diseño.

### I2 — Medir solo las funciones propias; la falla de un tercero es degradación

* Bueno, porque el objetivo se vuelve alcanzable y, por lo tanto, útil como driver de diseño.
* Bueno, porque obliga a diseñar explícitamente la degradación (QA-06), que es lo correcto con 12
  dependencias externas.
* Malo, porque el número de disponibilidad reportado puede ser mejor que la experiencia real del
  usuario. Mitigación obligatoria: la marca de frescura visible y el objetivo separado de QA-01.

### I3 — Un objetivo distinto por función

* Bueno, porque es lo más preciso y permite invertir el esfuerzo donde importa.
* Malo, porque con 15 requisitos funcionales serían demasiados objetivos que mantener y medir, lo
  que CON-09 no soporta.
* **Se adopta parcialmente:** el reparto en tres grupos (crítico / objetivo propio / fuera del
  objetivo) es I3 con una granularidad que el equipo puede sostener.

## Más información

* Drivers: [QA-05](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-05--pérdida-de-una-región-completa),
  [QA-06](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-06--indisponibilidad-de-un-proveedor-externo),
  [CRN-03](../01-analisis-inicial/06-concerns-arquitectonicos.md),
  [AMB-02](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución)
* Presupuesto: [presupuesto de error de disponibilidad](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-error-de-disponibilidad)
* Relacionados: [ADR-0002](ADR-0002-despliegue-multirregion.md) es la decisión de topología que este objetivo exige; la instrumentación concreta va en la [iteración 3](../02-proceso-add/iteracion-3-plan.md)
