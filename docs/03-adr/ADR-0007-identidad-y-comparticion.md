---
estado: aceptado
fecha: 2026-10-24
decisores: Ivo Iriarte, Jeremias Aguilar
consultados: Juan Emilio Pardo
informados: equipo completo
iteracion: 1
drivers: QA-12, QA-13, CON-08, RF-01, RF-11, RF-13, CRN-05, AMB-10
---

# ADR-0007: OIDC para la identidad, delegación OAuth para el correo y lista de designados para compartir

## Contexto y planteo del problema

El enunciado agrupa bajo «Seguridad y Privacidad» dos exigencias que suelen tratarse como una sola
y **no lo son**:

> «Debe garantizarse el acceso seguro y autorizado a los correos, y permitir el uso compartido de
> itinerarios asegurando que solo personas específicas designadas puedan visualizarlos.»

Son tres problemas distintos, con tres modelos de confianza distintos:

1. **Autenticar al usuario** de Trotamundos.
2. **Custodiar el acceso delegado a su correo.** El sistema guarda credenciales que dan acceso al
   buzón de 9 millones de personas (S-07). Es el activo más sensible que tiene, y
   [QA-13](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-13--intento-de-acceso-a-las-credenciales-de-correo)
   plantea el escenario del atacante que **ya está dentro** de un servicio.
3. **Autorizar a un tercero a ver un itinerario.** El designado no es un usuario del sistema del
   dueño del viaje: es alguien a quien se le dio acceso a un recurso ajeno.

Y hay un cuarto asunto que el refinado identificó como contradictorio con el tercero: el enunciado
también pide interoperar «con redes sociales para compartir itinerarios»
([AMB-10](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución)).
Publicar en una red social es, por definición, lo contrario de restringir a designados.

## Drivers de decisión

* **CON-08** — el acceso al correo requiere autorización explícita del usuario, y debe ser seguro.
  Es una restricción: no se negocia.
* **QA-13** — un servicio comprometido no debe poder descifrar tokens; detección de extracción
  masiva ≤ 5 min; revocación del 100 % de los tokens de una región ≤ 15 min.
* **QA-12** — 100 % de los accesos de no designados denegados y registrados; la respuesta de error
  no revela si el itinerario existe; caducidad a los 30 días y revocación efectiva en ≤ 60 s.
* **RF-01** — conectar una cuenta de correo y gestionar el ciclo de vida del consentimiento.
* **RF-11 / RF-13** — compartir con designados y publicar en redes sociales.
* **CRN-05** — gestión de secretos y tokens de terceros.

## Opciones consideradas

* **H1** — El sistema guarda las credenciales de correo del usuario.
* **H2** — OIDC para el usuario + OAuth 2.0 delegado para el correo, con los tokens en una bóveda
  de secretos.
* **H3** — Enlaces de capacidad para compartir: quien tiene el enlace, ve.
* **H4** — Lista de designados verificada contra la identidad autenticada del visitante.

## Resultado de la decisión

Se adopta **H2 para la identidad y el correo**, y **H4 para la compartición**. Son decisiones
separables pero se registran juntas porque comparten el elemento responsable.

### 1. Identidad del usuario

Autenticación delegada a un proveedor de identidad externo mediante **OpenID Connect** (E-14). El
sistema no almacena contraseñas de usuario.

### 2. Acceso al correo

Autorización delegada mediante **OAuth 2.0**: el consentimiento lo otorga el proveedor de correo,
con alcance acotado a lectura, y el usuario puede revocarlo en cualquier momento desde su
proveedor. En ningún momento se le pide la contraseña del correo (CON-08).

**La consecuencia estructural es la que importa:**

> `identity-access` es el **único** elemento del sistema con capacidad de descifrar un token de
> acceso a correo. `mail-ingest` —que es quien necesita leer los buzones— recibe **tokens de uso
> acotado y de vida corta**, emitidos por `identity-access` por buzón y por operación, y no tiene
> acceso a la bóveda de secretos.

Esto es lo que responde al escenario de QA-13: un `mail-ingest` comprometido no permite la
extracción masiva, porque no tiene de dónde extraer. El atacante obtendría, como máximo, los tokens
efímeros de las operaciones en curso.

### 3. Compartición con designados

El acceso a un itinerario compartido se decide contra la **identidad autenticada del visitante** y
su pertenencia a la lista de designados. El enlace identifica el recurso; **no otorga acceso**.

### 4. Publicación en redes sociales (resolución de AMB-10)

`sharing` expone **dos operaciones distintas**, no una con un parámetro:

| Operación | Modelo de confianza | Qué expone |
|---|---|---|
| `POST /viajes/{id}/comparticiones` | Control de acceso: lista de designados, autenticación obligatoria | El itinerario completo |
| `POST /viajes/{id}/publicaciones` | Divulgación voluntaria y pública | Un **resumen sin datos sensibles**: sin códigos de confirmación, sin números de documento, sin domicilios. Requiere confirmación explícita del usuario |

Son dos mecanismos porque son dos modelos de confianza. Unificarlos sería el camino directo a
filtrar un código de reserva en una red social.

### Consecuencias

* **Bueno,** porque CON-08 se satisface sin margen de interpretación: el sistema nunca ve la
  contraseña del correo del usuario.
* **Bueno,** porque la segmentación de privilegios acota el daño de un servicio comprometido, que
  es exactamente el modelo de amenaza de QA-13.
* **Bueno,** porque la revocación es doble: el usuario puede revocar desde su proveedor de correo,
  y el sistema puede revocar en bloque desde `identity-access`.
* **Bueno,** porque H4 cumple QA-12 de verdad: un enlace reenviado o filtrado no otorga acceso.
* **Bueno,** porque separar compartir de publicar elimina estructuralmente la posibilidad de
  divulgar datos sensibles por el canal equivocado.
* **Malo,** porque `identity-access` se convierte en un elemento crítico: si no está disponible, no
  se puede emitir tokens y la ingesta se detiene. Hay que replicarlo en las tres regiones y su
  disponibilidad pasa a ser parte del presupuesto de error.
* **Malo,** porque H4 impone fricción al designado: tiene que autenticarse para ver un itinerario
  que le compartieron. Se acepta, porque es lo que el driver exige; una alternativa de menor
  fricción incumpliría QA-12.
* **Malo,** porque la emisión de tokens de uso acotado por operación agrega latencia e
  indirección al camino de ingesta. El presupuesto de frescura de 300 s lo absorbe sin problema.
* **Neutro,** porque crea dependencia de un proveedor de identidad externo. Es la opción correcta
  bajo CON-09: operar autenticación propia es trabajo que el equipo no tiene disponible, y hacerlo
  mal es peor que delegarlo.

### Confirmación

* **Revisión de políticas de acceso:** verificar que ninguna identidad de carga de trabajo distinta
  de `identity-access` tiene permiso de descifrado sobre la bóveda de tokens. Es la verificación
  central de QA-13 y debe ser automatizada.
* **Prueba de QA-12:** intentar acceder a un itinerario compartido (a) sin autenticar, (b)
  autenticado como un usuario que no está en la lista. Las dos deben dar el mismo rechazo, y la
  respuesta no debe permitir distinguir si el itinerario existe.
* **Prueba de caducidad:** revocar una compartición y verificar que el acceso deja de funcionar en
  ≤ 60 s.
* **Prueba de publicación:** verificar que la carga útil de `publicaciones` no contiene ninguno de
  los campos sensibles declarados. Prueba automatizada sobre el contrato.
* **Prueba de revocación en bloque:** medir el tiempo de revocación de todos los tokens de una
  región. Debe ser ≤ 15 min.

## Pros y contras de las opciones

### H1 — El sistema guarda las credenciales de correo del usuario

* Bueno, porque funciona con cualquier proveedor de correo, incluido IMAP genérico, sin depender de
  que ofrezca OAuth.
* Bueno, porque es lo más simple de implementar.
* **Malo, porque viola CON-08:** pedirle al usuario la contraseña de su correo no es «acceso
  autorizado», y el usuario no puede revocar el acceso sin cambiar su contraseña.
* **Malo, porque es el peor caso posible de custodia:** una filtración entrega las cuentas de correo
  completas, no un acceso de lectura revocable.
* Nota: esto deja un hueco real para IMAP genérico (E-06), donde OAuth puede no estar disponible.
  Queda como asunto abierto de la iteración 4: o se exige OAuth y se limita la cobertura de IMAP, o
  se define un tratamiento específico y acotado. La decisión no se toma acá por falta de análisis.

### H2 — OIDC + OAuth 2.0 delegado con bóveda de secretos

* Bueno, porque satisface CON-08 y habilita QA-13 mediante segmentación de privilegios.
* Bueno, porque el consentimiento es explícito, de alcance acotado y revocable por el usuario.
* Bueno, porque delega la autenticación a un proveedor gestionado, lo que es correcto bajo CON-09.
* Malo, porque `identity-access` se vuelve crítico y hay que replicarlo en tres regiones.
* Malo, porque la emisión de tokens efímeros agrega indirección al camino de ingesta.

### H3 — Enlaces de capacidad (quien tiene el enlace, ve)

* Bueno, porque es la opción más simple y la de mejor experiencia: el designado abre el enlace y
  ve el itinerario, sin cuentas ni fricción.
* Bueno, porque no requiere que el designado tenga identidad en el sistema.
* **Malo, porque no cumple el driver.** QA-12 exige el 100 % de los accesos de no designados
  denegados, y un enlace reenviado, filtrado o capturado otorga acceso a quien no fue designado. La
  medida de respuesta del escenario es justamente lo que hace visible que la solución fácil no
  sirve.

### H4 — Lista de designados verificada contra la identidad autenticada

* Bueno, porque cumple QA-12 literalmente: el acceso depende de **ser** la persona designada, no de
  tener el enlace.
* Bueno, porque permite registrar quién accedió, que es lo que QA-14 va a necesitar.
* Bueno, porque la revocación es inmediata y verificable: se quita a la persona de la lista.
* Malo, porque impone fricción: el designado debe autenticarse.
* Malo, porque hay que resolver el caso del designado que no tiene cuenta. Queda para la iteración
  4, junto con el diseño de la interfaz de compartición.

## Más información

* Drivers: [QA-12](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-12--compartición-de-un-itinerario-con-personas-designadas),
  [QA-13](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-13--intento-de-acceso-a-las-credenciales-de-correo),
  [CON-08](../01-analisis-inicial/05-restricciones.md),
  [AMB-10](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución)
* Análisis comparativo: [iteración 1, paso 4, D7](../02-proceso-add/iteracion-1/paso-4-alternativas.md#d7--identidad-autorización-y-compartición)
* Asuntos abiertos para la iteración 4: tratamiento de IMAP sin OAuth; designado sin cuenta; detección de extracción masiva; rotación de claves
* Relacionados: [ADR-0004](ADR-0004-obtencion-de-correo.md) consume los tokens de uso acotado
