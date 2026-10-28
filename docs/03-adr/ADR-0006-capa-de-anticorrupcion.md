---
estado: aceptado
fecha: 2026-10-24
decisores: Juan Emilio Pardo, Jeremias Aguilar
consultados: Ivo Iriarte, Francisco Lozano
informados: equipo completo
iteracion: 1
drivers: QA-10, QA-11, QA-15, QA-06, CON-07, CON-04, CON-A3
---

# ADR-0006: Capa de anticorrupción con adaptadores cargados como complementos

## Contexto y planteo del problema

El [diagrama de contexto](../01-analisis-inicial/02-diagrama-de-contexto.md) mostró que **12 de las
16 interfaces del sistema son con terceros**: proveedores de correo, aerolíneas, hoteleras,
rentadoras, GDS, la agencia de viajes del usuario, redes sociales. Ninguno de esos contratos lo
controla Trotamundos, y cada uno tiene su propio modelo de datos, su propia disponibilidad y sus
propias cuotas.

Hay tres drivers que apuntan al mismo problema desde ángulos distintos:

* **QA-10** exige integrar un proveedor nuevo con **0 elementos existentes modificados** y ≤ 40
  horas-persona.
* **QA-15** exige incorporar un medio de transporte nuevo tocando **a lo sumo 2 elementos**, y
  ninguno de ellos un servicio de dominio.
* **QA-11** exige que un correo en formato desconocido **no corrompa el itinerario**: tasa de
  extracción incorrecta silenciosa = 0 %.

Si los servicios de dominio llamaran directamente a las APIs externas, los tres serían imposibles:
cada proveedor nuevo sería una modificación del dominio, y los conceptos ajenos —el modelo de datos
de NDC, el de HTNG, el formato de correo de cada aerolínea— se filtrarían al modelo canónico.

## Drivers de decisión

* **QA-10** — proveedor de viaje nuevo: 0 elementos modificados, ≤ 40 h-persona, ≥ 99 % de mensajes
  traducidos correctamente.
* **QA-11** — formato de correo desconocido: 0 % de extracción incorrecta silenciosa, ≥ 95 % de
  acierto en los 20 remitentes más frecuentes, extractor nuevo en ≤ 16 h-persona.
* **QA-15** — medio de transporte nuevo: ≤ 2 elementos modificados, ≤ 80 h-persona, sin cambios
  incompatibles en los contratos publicados.
* **QA-06** — la falla de un proveedor externo no debe propagarse al resto del sistema.
* **CON-07** — la integración debe hacerse mediante APIs estándar del dominio.
* **CON-04** — *spec-driven development*: la lógica tiene que ser verificable por contrato.

## Opciones consideradas

* **G1** — Llamadas directas desde los servicios de dominio.
* **G2** — Capa de anticorrupción con un adaptador por proveedor.
* **G3** — Plataforma de integración de terceros (iPaaS).
* **G4** — Capa de anticorrupción con los adaptadores cargados como complementos (*plugins*).

## Resultado de la decisión

Se adopta **G2 + G4**: una capa de anticorrupción cuyos adaptadores se **registran por
configuración** y no por despliegue conjunto.

### Estructura

```
Dominio (modelo canónico: Reserva · Segmento · Viaje)
          ▲
          │ contrato canónico de adaptador
          │
   ┌──────┴───────────────────────────────────────┐
   │        Capa de anticorrupción                │
   │                                              │
   │  provider-sync          booking-extraction   │
   │  ├─ adaptador NDC       ├─ extractor fmt. A  │
   │  ├─ adaptador OTA       ├─ extractor fmt. B  │
   │  ├─ adaptador rentadora ├─ extractor fmt. C  │
   │  └─ ⟨tren / autobús⟩    └─ ⟨formato nuevo⟩   │
   └──────────────────────────────────────────────┘
          │
   Sistemas externos (NDC, HTNG, APIs propietarias, correos)
```

### Las cuatro reglas de la decisión

1. **El dominio nunca ve un modelo externo.** Los adaptadores traducen al modelo canónico, en los
   dos sentidos. Ningún campo, código de error o concepto de un proveedor cruza la frontera.
2. **Un adaptador se agrega sin tocar los demás.** Implementa el contrato canónico y se registra
   por configuración. Esto es lo que hace que la medida de QA-10 —«0 elementos existentes
   modificados»— sea **literal** y no una aproximación.
3. **El mismo patrón se aplica dos veces.** A los proveedores de viaje en `provider-sync`, y a los
   formatos de correo en `booking-extraction`, donde cada extractor es un complemento. Son dos
   instancias del mismo concepto de diseño, no dos soluciones distintas.
4. **Cada extractor de correo devuelve un puntaje de confianza.** Si ningún extractor reconoce el
   formato con confianza suficiente, el sistema **no inventa**: registra la huella del formato para
   análisis y le ofrece al usuario la carga manual. Esto es lo que satisface el «0 % de extracción
   incorrecta silenciosa» de QA-11, y es una regla de la arquitectura, no de la implementación.

Además, **el cortacircuitos y el mamparo viven en el adaptador** (QA-06): cada proveedor tiene su
propio grupo de recursos y su propio cortacircuitos, de modo que un proveedor caído no agota las
conexiones de los demás ni propaga su falla al dominio.

### Consecuencias

* **Bueno,** porque QA-10, QA-11 y QA-15 se vuelven alcanzables con una sola decisión estructural.
* **Bueno,** porque aísla el ritmo de cambio: los proveedores externos cambian sus APIs cuando
  quieren, y el impacto queda confinado a un adaptador.
* **Bueno,** porque QA-06 queda naturalmente ubicado: el cortacircuitos está donde está la falla.
* **Bueno,** porque la regla del puntaje de confianza convierte una preocupación de calidad de
  datos en una propiedad verificable de la arquitectura.
* **Malo,** porque agrega una capa de indirección y un contrato interno más que diseñar, versionar
  y documentar.
* **Malo,** porque **el contrato canónico de adaptador es ahora un punto crítico de diseño**: si se
  define demasiado estrecho, un proveedor con un modelo distinto no encaja y hay que modificar el
  contrato —rompiendo exactamente la propiedad que se buscaba. Esto es el **riesgo R-2**, y es la
  razón por la que el modelo canónico es el objetivo central de la iteración 2.
* **Neutro,** porque los adaptadores concretos de tren y autobús **no** se construyen (CON-A3):
  solo se garantiza que el punto de extensión existe.

### Confirmación

* **Prueba de QA-10:** implementar un adaptador de proveedor ficticio en el prototipo y verificar
  por el historial del repositorio que **ningún archivo** de un servicio de dominio ni de otro
  adaptador fue modificado.
* **Prueba de QA-11:** alimentar el prototipo con un correo de formato desconocido y verificar que
  no se crea ninguna reserva y que queda registrado el caso. Debe ser una prueba automatizada.
* **Verificación de la frontera:** análisis estático que falle si un servicio de dominio importa un
  tipo de un modelo externo.
* **Prueba de contrato:** cada adaptador se verifica contra el contrato canónico con pruebas de
  contrato (CON-04, [ADR-0009](ADR-0009-contratos-spec-driven.md)).

## Pros y contras de las opciones

### G1 — Llamadas directas desde los servicios de dominio

* Bueno, porque es lo más simple y lo más directo: menos elementos, menos indirección.
* Bueno, porque no hay que diseñar ningún contrato interno adicional.
* **Malo, porque cada proveedor nuevo modifica el dominio**, lo que contradice la medida de QA-10
  de forma frontal.
* **Malo, porque los conceptos del proveedor se filtran al modelo canónico**, que es precisamente
  lo que hace que agregar un medio de transporte nuevo (QA-15) termine tocando todo.
* Malo, porque la falla de un tercero se propaga al dominio (QA-06).

### G2 — Capa de anticorrupción con un adaptador por proveedor

* Bueno, porque contiene la heterogeneidad y el ritmo de cambio ajeno.
* Bueno, porque ubica naturalmente el cortacircuitos y el mamparo.
* Malo, porque si los adaptadores se despliegan junto con el servicio, agregar uno obliga a
  redesplegar los demás: la medida de QA-10 se cumple «casi». De ahí G4.

### G3 — Plataforma de integración de terceros (iPaaS)

* Bueno, porque agregar un proveedor sería configuración y no desarrollo.
* Bueno, porque la plataforma ya resuelve reintentos, transformaciones y monitoreo.
* **Malo, porque saca la lógica de traducción del repositorio**, y CON-04 exige que esté
  versionada y verificable por pruebas de contrato. Es el motivo decisivo del descarte.
* Malo, porque agrega una dependencia de proveedor más, con su propia disponibilidad y su propio
  costo, en el camino crítico de QA-01.

### G4 — Adaptadores cargados como complementos

* Bueno, porque hace literal la medida de QA-10: el adaptador se registra por configuración, sin
  redesplegar los existentes.
* Bueno, porque permite habilitar y deshabilitar un proveedor en caliente, lo cual es útil durante
  una falla de ese proveedor.
* Malo, porque exige definir y versionar el contrato del complemento, que es trabajo de diseño
  adicional.
* Malo, porque la carga dinámica agrega superficie de ataque: un complemento es código que se
  ejecuta en el proceso. Mitigación: los complementos son parte del repositorio y pasan por el
  mismo control de cambios, no se cargan desde fuentes externas.

## Más información

* Drivers: [QA-10](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-10--integración-de-un-proveedor-de-viaje-nuevo),
  [QA-11](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-11--formato-de-correo-desconocido),
  [QA-15](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-15--incorporar-un-nuevo-medio-de-transporte),
  [CON-07](../01-analisis-inicial/05-restricciones.md)
* Análisis comparativo: [iteración 1, paso 4, D6](../02-proceso-add/iteracion-1/paso-4-alternativas.md#d6--integración-con-sistemas-externos)
* Riesgo que genera: [R-2 (fragilidad de la extracción desde correo)](../02-proceso-add/iteracion-1/paso-7-analisis.md#riesgos-residuales)
* Relacionados: el modelo canónico que este ADR presupone se diseña en la [iteración 2](../02-proceso-add/iteracion-2-plan.md); el versionado del contrato de adaptador, en la [iteración 4](../02-proceso-add/iteracion-4-plan.md)
