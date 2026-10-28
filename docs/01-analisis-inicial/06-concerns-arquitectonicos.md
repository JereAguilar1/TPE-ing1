# 1.6 Inquietudes arquitectónicas

Las *inquietudes arquitectónicas* (**architectural concerns**) son asuntos que el arquitecto debe
atender aunque no vengan expresados como requisito. ADD las toma como una de las cuatro categorías
de drivers de entrada, al mismo nivel que los requisitos funcionales y los escenarios de calidad.

Se distinguen dos grupos: las que vienen del tipo de sistema y del contexto del proyecto, y las
que surgen del propio diseño a medida que avanza.

## Inquietudes generales del sistema y del proyecto

| ID | Inquietud | Por qué importa | Dónde se atiende |
|---|---|---|---|
| **CRN-01** | **Establecer la estructura general del sistema.** Es un sistema *greenfield* y novedoso: no hay base de código previa ni arquitectura de referencia establecida para el dominio | Sin una estructura general no hay dónde ubicar la funcionalidad primaria ni a qué aplicar tácticas de calidad. Es la inquietud que define el objetivo de la primera iteración | [Iteración 1](../02-proceso-add/iteracion-1/README.md) |
| **CRN-02** | **Asignar trabajo a un equipo de 4 personas con dedicación parcial.** La estructura del sistema condiciona cómo se puede repartir el trabajo (ley de Conway en sentido inverso) | Una descomposición con 30 servicios es indocumentable e inconstruible por este equipo; una con 2 no permite trabajar en paralelo | [Iteración 1](../02-proceso-add/iteracion-1/README.md) (CON-A4) y [reparto de trabajo](../00-gestion/equipo.md#reparto-de-trabajo-por-iteración) |
| **CRN-03** | **Gestionar el presupuesto de error de disponibilidad.** 5 minutos al mes es un presupuesto que se consume, y hay que poder saber cuánto queda | Sin instrumentación y objetivos de nivel de servicio explícitos, el objetivo de disponibilidad es una aspiración y no un driver verificable | [ADR-0008](../03-adr/ADR-0008-alcance-disponibilidad.md) e [iteración 3](../02-proceso-add/iteracion-3-plan.md) |
| **CRN-04** | **Desplegar continuamente sin inactividad.** Con 5 minutos al mes no hay ventana de mantenimiento posible | Condiciona la estructura: los elementos deben ser reemplazables de forma independiente y los cambios de esquema de datos tienen que ser compatibles hacia atrás | QA-07, [iteración 3](../02-proceso-add/iteracion-3-plan.md) |
| **CRN-05** | **Gestionar secretos y tokens de terceros.** El sistema custodia tokens que dan acceso al correo de 9 millones de personas | Es el activo más sensible del sistema y el de mayor impacto reputacional si se filtra | QA-13, [ADR-0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [iteración 4](../02-proceso-add/iteracion-4-plan.md) |
| **CRN-06** | **Estrategia de pruebas y de verificación de contratos.** El enfoque *spec-driven* exige que los contratos sean verificables, no solo declarados | Sin pruebas de contrato, «consistente con la arquitectura documentada» no se puede demostrar, que es justamente lo que §5 del enunciado evalúa | [ADR-0009](../03-adr/ADR-0009-contratos-spec-driven.md), [iteración 2](../02-proceso-add/iteracion-2-plan.md) |
| **CRN-07** | **Trazabilidad driver → decisión → vista → código.** Es a la vez un requisito de calidad (QA-16) y un criterio de evaluación del trabajo | Obliga a una convención de identificadores estable y a la [matriz de trazabilidad](../05-trazabilidad/matriz-drivers-decisiones.md) |  Transversal a todas las iteraciones |
| **CRN-08** | **Costo de infraestructura.** Un despliegue activo-activo en tres regiones con plano analítico propio es caro para una *startup* | El costo es una fuerza real contra el objetivo de disponibilidad, y la decisión de cuánto gastar es arquitectónica | [ADR-0002](../03-adr/ADR-0002-despliegue-multirregion.md) |
| **CRN-09** | **Cuotas y límites de tasa de las APIs de terceros.** Las APIs de correo y de proveedores de viaje imponen cuotas que el sistema no controla | Es la restricción que vuelve inviable el sondeo uniforme y la que puede frenar el crecimiento de QA-08 | [ADR-0004](../03-adr/ADR-0004-obtencion-de-correo.md), [iteración 3](../02-proceso-add/iteracion-3-plan.md) |
| **CRN-10** | **Internacionalización desde el inicio.** Agregar i18n a un sistema que no la previó es un retrabajo que atraviesa todas las capas | El enunciado pide estar «preparado arquitectónicamente» para el mercado internacional, lo cual es exactamente una inquietud arquitectónica y no un requisito funcional | QA-18, [iteración 4](../02-proceso-add/iteracion-4-plan.md) |

## Inquietudes que surgirán del diseño

Estas se registran por adelantado porque se sabe que van a aparecer, y así quedan asignadas a una
iteración en lugar de descubrirse tarde:

| ID | Inquietud | Iteración donde se atiende |
|---|---|---|
| CRN-11 | Resolución de conflictos cuando dos fuentes (correo, proveedor, alta manual) describen la misma reserva de forma distinta | 2 |
| CRN-12 | Idempotencia de la ingesta: el mismo correo o la misma notificación pueden llegar más de una vez | 2 |
| CRN-13 | Consistencia de datos entre regiones activas y qué se sacrifica cuando se parten | 3 |
| CRN-14 | Versionado y evolución de los contratos publicados sin romper consumidores | 4 |
| CRN-15 | Residencia de datos: qué datos pueden salir de la región del usuario y cuáles no | 4 |
