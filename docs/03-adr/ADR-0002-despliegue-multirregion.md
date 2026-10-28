---
estado: aceptado
fecha: 2026-10-24
decisores: Francisco Lozano, Jeremias Aguilar
consultados: Juan Emilio Pardo, Ivo Iriarte
informados: equipo completo
iteracion: 1
drivers: QA-05, QA-02, QA-03, QA-18, CRN-08, CRN-13, CON-A2, AMB-06
---

# ADR-0002: Despliegue activo-activo en tres regiones

## Contexto y planteo del problema

El enunciado fija un objetivo de disponibilidad de **5 minutos de inactividad no planificada por
mes**, equivalente al **99,9884 %**. Es un objetivo que no se alcanza por casualidad: define la
topología de despliegue.

El [reparto del presupuesto de error](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-error-de-disponibilidad)
asigna **2 minutos al plano de datos**, de los cuales
[QA-05](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-05--pérdida-de-una-región-completa)
tolera como máximo **1,5 minutos** para el caso de pérdida de una región completa. Ese número es
el que decide: un *failover* de activo a pasivo —detectar, promover el almacén, redirigir el
tráfico, recalentar las cachés— tarda realistamente varios minutos. **Un solo incidente al año
agotaría el presupuesto mensual completo.**

Hay un segundo driver que empuja en la misma dirección: el sistema es de uso global (AMB-06,
QA-18) y el [presupuesto de latencia de QA-02](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-latencia-web-800-ms-p95)
asigna solo **120 ms** a la red del cliente hasta el borde. Desde una región única, los usuarios de
las otras dos franjas horarias pagarían latencia transoceánica y ese tramo no cerraría.

Y hay una fuerza en contra, que es real y no se puede ignorar: **el costo** (CRN-08). Trotamundos
es una *startup*, y el activo-activo implica pagar capacidad en tres lugares.

## Drivers de decisión

* **QA-05** — pérdida de una región completa: detección ≤ 30 s, redirección ≤ 60 s, 0 pérdida de
  datos confirmados, ≤ 1,5 min de presupuesto mensual consumido.
* **QA-02 / QA-03** — el tramo de red de 120 ms del presupuesto de latencia solo cierra si el
  borde está cerca del usuario.
* **QA-18 / AMB-06** — operación en tres regiones (América, Europa, Asia-Pacífico), con residencia
  de datos por región.
* **CRN-08** — el costo de infraestructura es una fuerza real contra este objetivo.
* **CON-A2** — se asume nube pública con al menos tres regiones.

## Opciones consideradas

* **B1** — Región única con múltiples zonas de disponibilidad.
* **B2** — Activo-pasivo multirregión.
* **B3** — Activo-activo en tres regiones.
* **B4** — Activo-activo en más de tres regiones.

## Resultado de la decisión

Se adopta **B3: activo-activo en tres regiones** (América, Europa, Asia-Pacífico), con enrutamiento
geográfico en el borde y comprobación de salud por región.

Las tres regiones **sirven tráfico simultáneamente**. La pérdida de una no es una conmutación: es
una redistribución del tráfico entre las que quedan, lo cual es lo que permite entrar en el
presupuesto de 1,5 minutos.

Se decide además que **tres es el número**, y no más: es el mínimo que cubre las tres franjas
horarias y que sobrevive a la pérdida de una conservando mayoría para los mecanismos de consenso
del plano de datos.

### Consecuencias

* **Bueno,** porque QA-05 se vuelve alcanzable: no hay conmutación que consuma el presupuesto.
* **Bueno,** porque acerca el borde al usuario, que es lo que financia el tramo de 120 ms del
  presupuesto de latencia de QA-02 y QA-03.
* **Bueno,** porque habilita la residencia de datos por región que CON-10 y CRN-15 van a exigir en
  la iteración 4: cada región puede ser la residencia primaria de los datos de sus usuarios.
* **Bueno,** porque elimina la necesidad de ventanas de mantenimiento: se puede desplegar región
  por región (lo que QA-07 necesita).
* **Malo,** porque el costo de infraestructura se triplica, más el tráfico de replicación entre
  regiones. Es el **riesgo R-3** del [análisis de la iteración 1](../02-proceso-add/iteracion-1/paso-7-analisis.md#riesgos-residuales).
* **Malo, y esto es lo más importante: traslada el problema a la consistencia de datos entre
  regiones.** Con tres regiones aceptando escrituras, dos actualizaciones concurrentes sobre el
  mismo viaje —el usuario editando desde una región mientras un proveedor notifica un cambio hacia
  otra— pueden divergir. Si se resuelve mal, el usuario ve dos versiones distintas de su itinerario
  según desde dónde consulte, lo que contradice directamente la meta MN-1 de ser el único punto de
  verdad. Queda registrado como **riesgo R-1** y asignado a CRN-13 en la iteración 3.
* **Neutro,** porque la operación se vuelve más compleja: hay que ejercitar regularmente la pérdida
  de una región para confiar en el mecanismo, y eso es trabajo de operación continuo.

### Confirmación

* **Ejercicio de caída de región:** retirar una región del enrutamiento en el entorno de pruebas y
  medir tiempo de detección, tiempo de redirección y pérdida de datos. Debe dar ≤ 30 s, ≤ 60 s y 0
  respectivamente.
* **Medición de latencia por región:** el p95 del tramo cliente-borde debe estar por debajo de los
  120 ms asignados, desde cada una de las tres regiones.
* **Verificación de la topología:** la [vista de despliegue](../04-vistas/vista-despliegue-nivel-1.md)
  debe coincidir con la infraestructura declarada como código del prototipo.

## Pros y contras de las opciones

### B1 — Región única con múltiples zonas de disponibilidad

* Bueno, porque es el más barato (CRN-08) y la consistencia es trivial.
* Bueno, porque es el más simple de operar, lo que importa con CON-09.
* **Malo, porque una región caída es una caída total:** el primer incidente del año agota el
  presupuesto anual de 60 minutos. Incompatible con QA-05 por definición.
* Malo, porque los usuarios de las otras dos franjas horarias pagan latencia transoceánica y el
  tramo de red del presupuesto de QA-02 no cierra.
* Malo, porque no habilita residencia de datos por región (CON-10).

### B2 — Activo-pasivo multirregión

* Bueno, porque cuesta menos que el activo-activo: la región pasiva puede estar dimensionada por
  debajo.
* Bueno, porque la replicación es en un solo sentido, de modo que **no** aparece el problema de
  consistencia del activo-activo.
* **Malo, porque el tiempo de recuperación del *failover* consume el presupuesto entero.** Es el
  argumento decisivo: el presupuesto es de 5 minutos al mes y un *failover* realista está en ese
  mismo orden de magnitud.
* Malo, porque hay que ejercitar el *failover* para confiar en él, y un *failover* que no se
  ejercita no funciona cuando hace falta.
* Malo, porque la región pasiva no sirve tráfico: se paga capacidad ociosa y no se gana nada de
  latencia.

### B3 — Activo-activo en tres regiones

* Bueno, porque resuelve QA-05 sin conmutación, y mejora QA-02 y QA-18 de paso.
* Malo, porque triplica el costo (R-3).
* Malo, porque introduce el problema de consistencia entre regiones (R-1), que es el riesgo técnico
  más difícil del sistema.

### B4 — Activo-activo en más de tres regiones

* Bueno, porque mejora marginalmente la latencia y la tolerancia a fallas.
* Malo, porque el costo crece sin ganancia proporcional sobre el driver: QA-05 habla de perder
  **una** región, y tres ya lo resuelven.
* Malo, porque agrava el problema de consistencia: más réplicas aceptando escrituras es más
  divergencia posible.

## Más información

* Drivers: [QA-05](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-05--pérdida-de-una-región-completa),
  [AMB-06 y el presupuesto de error](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-error-de-disponibilidad)
* Análisis comparativo: [iteración 1, paso 4, D2](../02-proceso-add/iteracion-1/paso-4-alternativas.md#d2--topología-de-despliegue)
* Vista afectada: [despliegue N1](../04-vistas/vista-despliegue-nivel-1.md)
* Riesgos que genera: [R-1 (consistencia) y R-3 (costo)](../02-proceso-add/iteracion-1/paso-7-analisis.md#riesgos-residuales)
* Relacionados: [ADR-0008](ADR-0008-alcance-disponibilidad.md) acota qué se mide; [ADR-0001](ADR-0001-estilo-arquitectonico.md) hace replicables los elementos
