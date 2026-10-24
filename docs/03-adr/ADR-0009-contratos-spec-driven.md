---
estado: aceptado
fecha: 2026-10-24
decisores: Jeremias Aguilar, Juan Emilio Pardo
consultados: Francisco Lozano, Ivo Iriarte
informados: equipo completo
iteracion: 1
drivers: CON-04, CON-02, QA-16, QA-10, CRN-06, CRN-07, CRN-14
---

# ADR-0009: Los contratos de interfaz son artefactos de primera clase

## Contexto y planteo del problema

El enunciado establece dos cosas que juntas determinan esta decisión:

> §4: «Se recomienda enfáticamente adoptar un enfoque de *Spec-driven development* tanto para el
> diseño con ADD como para las tareas de implementación del prototipo.»
>
> §5: «Se evaluará que el código del prototipo sea trazable, consistente con la arquitectura
> documentada y respete las especificaciones definidas **contractualmente**.»

Esto no se cumple documentando las interfaces después de implementarlas. «Respetar las
especificaciones definidas contractualmente» exige que el contrato **exista antes** y que la
consistencia sea **verificable**, no afirmada.

Hay además una necesidad propia del diseño: [ADR-0001](ADR-0001-estilo-arquitectonico.md) produjo
13 elementos que se comunican por dos medios distintos (HTTP sincrónico y eventos asíncronos), y
[ADR-0006](ADR-0006-capa-de-anticorrupcion.md) introdujo un contrato canónico de adaptador del que
depende la medida de QA-10. Sin contratos explícitos, nada de eso es verificable.

## Drivers de decisión

* **CON-04** — *spec-driven development*; el prototipo debe respetar especificaciones contractuales.
* **CON-02** — las decisiones se documentan como ADRs; los contratos son la contraparte ejecutable.
* **QA-16** — trazabilidad driver → decisión → vista → **contrato** → código, en ≤ 10 min.
* **QA-10** — «0 elementos modificados» al agregar un adaptador solo es verificable contra un
  contrato.
* **CRN-06** — estrategia de pruebas y verificación de contratos.
* **CRN-14** — versionado y evolución de los contratos publicados.

## Opciones consideradas

* **J1** — Documentar las interfaces en prosa, dentro de la wiki.
* **J2** — Generar la documentación de las interfaces a partir del código ya escrito.
* **J3** — Contratos como artefactos versionados, escritos antes del código y verificados por
  pruebas de contrato.

## Resultado de la decisión

Se adopta **J3**. Concretamente:

| Tipo de interfaz | Formato del contrato | Qué especifica |
|---|---|---|
| Interfaces sincrónicas (HTTP/JSON) | **OpenAPI** | Rutas, esquemas de petición y respuesta, códigos de error, requisitos de autorización |
| Interfaces asíncronas (eventos de dominio) | **AsyncAPI** | Nombre del evento, esquema de la carga útil, clave de partición, garantías de entrega |
| Contrato canónico de adaptador | Esquema del modelo canónico + interfaz del complemento | Qué debe implementar un adaptador nuevo para encajar |

### Las cuatro reglas

1. **El contrato se escribe antes de la implementación.** El contrato es la especificación; el
   código es su realización. No al revés.
2. **El contrato vive en el repositorio y está versionado.** No es un documento aparte que se
   desincroniza: es un archivo que cambia por *pull request* como el código.
3. **La consistencia se verifica por pruebas de contrato, no por revisión.** Cada consumidor
   verifica contra el contrato del proveedor en la integración continua. Si la implementación se
   aparta del contrato, la construcción falla.
4. **Cada contrato referencia los drivers y el ADR que lo justifican.** Es el eslabón que cierra la
   cadena de QA-16 entre la decisión y el código.

### Consecuencias

* **Bueno,** porque CON-04 y el criterio de evaluación de §5 se vuelven verificables en lugar de
  declarativos: hay una prueba que falla si el código se aparta de lo documentado.
* **Bueno,** porque cierra la cadena de trazabilidad de QA-16: driver → ADR → vista → contrato →
  código, recorrible en los dos sentidos.
* **Bueno,** porque hace literal la medida de QA-10: «agregar un adaptador sin modificar nada» se
  comprueba viendo que el contrato canónico no cambió.
* **Bueno,** porque permite trabajar en paralelo, lo cual importa con CON-09: acordado el contrato,
  dos integrantes pueden implementar los dos lados a la vez.
* **Bueno,** porque los contratos son el insumo natural de la iteración 2: definir el contrato de
  un elemento **es** definir su interfaz, que es el paso 5 de ADD.
* **Malo,** porque escribir el contrato primero es más lento al principio, y con CON-09 el tiempo
  es el recurso escaso. La contrapartida es que evita el retrabajo de integración, que es más caro.
* **Malo,** porque un contrato mal diseñado es más difícil de cambiar que un código mal diseñado:
  tiene consumidores. Esto obliga a resolver el versionado (CRN-14), que queda asignado a la
  iteración 4.
* **Neutro,** porque exige herramienta de verificación de contratos en la integración continua. Es
  trabajo de preparación que se amortiza.

### Confirmación

* **Cobertura de contratos:** el 100 % de las interfaces entre elementos de la
  [vista C&C](../04-vistas/vista-cyc-nivel-1.md) tiene un contrato OpenAPI o AsyncAPI en el
  repositorio. Verificable por conteo contra la vista.
* **Verificación en la integración continua:** la construcción falla si una implementación se
  aparta de su contrato, o si un contrato cambia de forma incompatible sin cambiar su versión.
* **Prueba de trazabilidad (QA-16):** tomar un elemento al azar del prototipo y recorrer en ≤ 10
  min la cadena hasta el driver que lo justifica, usando solo la wiki y el repositorio.

## Pros y contras de las opciones

### J1 — Documentar las interfaces en prosa dentro de la wiki

* Bueno, porque es rápido de escribir y de leer.
* Bueno, porque no requiere herramientas ni preparación.
* **Malo, porque no es verificable:** nada impide que el código diverja de la prosa, y la
  divergencia es silenciosa.
* Malo, porque no sirve para generar clientes ni pruebas, de modo que todo el trabajo de
  integración se hace a mano.
* Malo, porque incumple CON-04: no hay especificación «contractual», hay descripción.

### J2 — Generar la documentación a partir del código

* Bueno, porque la documentación nunca se desincroniza del código: se deriva de él.
* Bueno, porque es el camino de menor esfuerzo continuo.
* **Malo, porque invierte la relación que CON-04 pide:** el código pasa a ser la especificación, y
  la documentación su reflejo. Un cambio incompatible en el código se documenta prolijamente como
  si estuviera bien.
* Malo, porque impide trabajar en paralelo: no hay contrato hasta que alguien escribió el código.
* Malo, porque no permite verificar nada: comparar el código con su propia derivación es una
  tautología.

### J3 — Contratos versionados escritos antes del código, verificados por pruebas

* Bueno, porque cumple CON-04 y hace verificable el criterio de evaluación de §5.
* Bueno, porque habilita trabajo en paralelo y generación de clientes y validadores.
* Bueno, porque encaja exactamente con el paso 5 de ADD («definir interfaces»).
* Malo, porque es más lento al inicio.
* Malo, porque obliga a resolver el versionado de contratos (CRN-14).

## Más información

* Drivers: [CON-04 y CON-02](../01-analisis-inicial/05-restricciones.md),
  [QA-16](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-16--trazabilidad-de-una-decisión-al-código),
  [CRN-06 y CRN-14](../01-analisis-inicial/06-concerns-arquitectonicos.md)
* Interfaces a especificar: [paso 5 de la iteración 1](../02-proceso-add/iteracion-1/README.md#paso-5--instanciar-elementos-asignar-responsabilidades-y-definir-interfaces)
* Los contratos concretos se escriben en la [iteración 2](../02-proceso-add/iteracion-2-plan.md); su versionado se resuelve en la [iteración 4](../02-proceso-add/iteracion-4-plan.md)
