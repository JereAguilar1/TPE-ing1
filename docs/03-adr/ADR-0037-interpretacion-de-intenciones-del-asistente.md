---
estado: aceptado
fecha: 2026-11-17
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 5
drivers: RF-B1, RF-B2, QA-13, QA-14, QA-16, QA-18, CRN-10, CON-04, CON-05, CON-09, CON-10
---

# ADR-0037: El asistente entiende por intenciones detrás de un intérprete intercambiable: reglas en el prototipo y un modelo de lenguaje enchufable, con datos personales redactados

## Contexto y planteo del problema

El asistente virtual (Opción B, [ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md)) recibe
texto libre: «¿a qué hora sale mi vuelo?», «me pasaron el vuelo al jueves a las 18:30», «quiero
hablar con mi agencia». Antes de actuar tiene que saber **qué pide** el viajero (la intención) y
**sobre qué** (el viaje, la reserva, la fecha y la hora nuevas).

Hay dos formas conocidas de resolverlo, y tiran en direcciones opuestas. Un modelo de lenguaje
entiende mucho mejor el texto libre, pero cada mensaje viajaría a un tercero con datos personales
(nombres, localizadores, destinos: [CON-10](../01-analisis-inicial/05-restricciones.md), QA-14), su
salida no es determinista (no se puede probar con aserciones exactas, QA-16) y necesita una clave paga
que la integración continua no debería tener. Las reglas son predecibles, gratuitas y probables, pero
entienden solo lo que se previó.

La iteración 4 ya había dejado una pista en su verificación en papel: el asistente «redacta datos
personales innecesarios antes de invocar cualquier modelo lingüístico externo». No decidía si se usa
uno.

## Drivers de decisión

* **RF-B1** — atender consultas de estado, reprogramaciones y problemas menores.
* **RF-B2** — derivar a la agencia solo lo que el bot no resuelve: un malentendido no puede terminar
  en una acción equivocada.
* **QA-13 / QA-14 / CON-10** — datos personales: minimización y control de a quién se envían.
* **QA-16 / CON-04** — el prototipo tiene que ser trazable y verificable con pruebas.
* **CON-05 / CON-09** — alcance acotado y cuatro personas con dedicación parcial.
* **QA-18 / CRN-10** — ningún texto para el usuario fijo en el código de un servicio
  ([ADR-0032](ADR-0032-internacionalizacion-y-localizacion.md)).

## Opciones consideradas

* **I1** — Solo reglas: palabras clave y patrones dentro del asistente.
* **I2** — Solo un modelo de lenguaje externo, que recibe el mensaje y devuelve la intención.
* **I3** — Un puerto `InterpreteDeIntenciones` con la misma salida para cualquier implementación:
  reglas en el prototipo y un adaptador de modelo de lenguaje enchufable, con datos personales
  redactados antes de salir.

## Resultado de la decisión

Se adopta **I3**:

1. **Un puerto, una salida.** El asistente depende de `InterpreteDeIntenciones`, que recibe el texto
   y el contexto del viajero (sus viajes y reservas) y devuelve una `Interpretacion`: la intención
   (el enum `Intencion` de `contratos/openapi/virtual-assistant.yaml`), las entidades encontradas
   (viaje, reserva por su referencia, fecha y hora nuevas) y una confianza entre 0 y 1. El resto del
   asistente no sabe qué implementación respondió.
2. **El prototipo usa reglas.** Patrones en español rioplatense por intención, extracción de fechas
   y horas relativas a la zona del tramo, y búsqueda de la reserva por referencia (`AR1402`) o, si no
   hay, por el próximo tramo del viaje. Es determinista: cada regla tiene su prueba.
3. **El modelo de lenguaje queda diseñado y enchufable, no construido.** Un adaptador detrás del mismo
   puerto. Antes de enviar el texto, un redactor reemplaza por marcadores los datos que el modelo no
   necesita para clasificar (correos, teléfonos, localizadores, nombres propios del contexto) y los
   restituye en la respuesta. Si el modelo no responde o devuelve una intención fuera del enum, se
   usa la interpretación por reglas. La clave del modelo es un secreto de operación, nunca del código.
4. **Por debajo del umbral, `noEntendido`.** Una interpretación con confianza menor a **0,6** (el
   mismo umbral bajo de [ADR-0015](ADR-0015-politica-de-confianza-de-extraccion.md), supuesto a
   calibrar) se trata como no entendida: el asistente repregunta en vez de adivinar, y eso alimenta la
   derivación de [ADR-0039](ADR-0039-politica-de-derivacion-a-la-agencia.md).
5. **Ni las reglas ni las respuestas están fijas en el código** ([ADR-0032](ADR-0032-internacionalizacion-y-localizacion.md)).
   Los patrones de cada intención forman un **catálogo por idioma**, y lo que el asistente le dice al
   viajero sale de un **catálogo de mensajes** con marcadores (`ICU MessageFormat`), elegido por el
   idioma de la sesión. Las fechas y horas se formatean en la zona horaria del lugar del tramo. El
   prototipo trae solo los catálogos en español rioplatense; otro idioma es otro par de catálogos,
   sin tocar el código.

### Consecuencias

* **Bueno,** porque el prototipo es determinista y probable con aserciones exactas, y la integración
  continua no necesita secretos ni costo por mensaje.
* **Bueno,** porque pasar a un modelo de lenguaje es agregar un adaptador, sin tocar el resto del
  asistente: la misma idea de complementos de [ADR-0006](ADR-0006-capa-de-anticorrupcion.md).
* **Bueno,** porque ningún dato personal sale del sistema mientras se usen reglas, y si se enchufa un
  modelo, sale redactado.
* **Malo,** porque las reglas entienden solo lo que se previó: frases fuera de los patrones terminan
  en `noEntendido`. Se mitiga con la repregunta y con la derivación tras dos intentos (ADR-0039).
* **Neutro,** porque la calidad de comprensión del prototipo no representa la de producción; el
  diseño sí.

### Confirmación

* Pruebas por intención con frases de ejemplo y sus entidades esperadas, incluidas fechas relativas
  («el jueves», «mañana a las 9») en la zona horaria del tramo.
* Prueba de que una frase fuera de los patrones devuelve `noEntendido` y no una acción.
* Prueba de arquitectura: ningún módulo del asistente salvo el intérprete conoce cómo se interpreta.
* Prueba de que el código del asistente no tiene textos para el usuario: todos salen del catálogo.

## Pros y contras de las opciones

### I1 — Solo reglas

* Bueno, porque es determinista, gratuito y sin datos que salgan.
* Malo, porque cierra la puerta a mejorar la comprensión sin reescribir el asistente.

### I2 — Solo un modelo de lenguaje externo

* Bueno, porque entiende texto libre mucho mejor y luce en una demostración.
* Malo, porque envía datos personales a un tercero en cada mensaje (CON-10), no es probable con
  aserciones exactas (QA-16) y necesita una clave paga en la integración continua.
* Malo, porque una caída del proveedor deja al asistente sin comprensión alguna.

### I3 — Puerto con reglas y modelo enchufable

* Bueno, porque toma lo mejor de I1 para el prototipo sin cerrar el camino de I2.
* Malo, porque agrega una pieza (el puerto y el redactor) que el prototipo no aprovecha del todo.

## Más información

* Iteración: [iteración 5, paso 4, D37](../02-proceso-add/iteracion-5/paso-4-alternativas.md#d37--cómo-entiende-el-asistente-lo-que-escribe-el-viajero-rf-b1-qa-14)
* Contrato: [`virtual-assistant.yaml`](../../contratos/openapi/virtual-assistant.yaml) (enum `Intencion`)
* Relacionados: [ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md), [ADR-0038](ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md), [ADR-0039](ADR-0039-politica-de-derivacion-a-la-agencia.md), [ADR-0040](ADR-0040-sesion-conversacional-y-privacidad.md)
