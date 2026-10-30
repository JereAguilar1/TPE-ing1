---
estado: aceptado
fecha: 2026-10-29
decisores: Ivo Iriarte, Juan Emilio Pardo
consultados: Jeremias Aguilar, Francisco Lozano
informados: equipo completo
iteracion: 4
drivers: QA-12, QA-14, RF-11, RF-13, AMB-10
---

# ADR-0028: Autorización declarativa ABAC con vales firmados, acceso OTP para designados sin cuenta y publicación por lista blanca

## Contexto y planteo del problema

[ADR-0007](ADR-0007-identidad-y-comparticion.md) estableció tres principios estructurales: federación
OpenID Connect para identificar personas, compartición de itinerarios restringida a una lista nominal
de designados (`QA-12`) y separación entre compartir con personas designadas (`RF-11`) y publicar un
resumen en redes sociales (`RF-13` / `AMB-10`). Quedaron deliberadamente abiertos para esta iteración
tres problemas concretos:

1. **El designado sin cuenta previa:** cuando un viajero comparte su viaje con un familiar o colega
   cuyo correo figura en `designados` pero que nunca usó Trotamundos, ¿cómo se verifica su identidad
   respetando el **`100 %` de bloqueo a terceros no designados** de `QA-12` sin rebajar el esquema a un
   enlace de capacidad reenviable ni forzar el alta pesada de una cuenta permanente (`CON-10`)?
2. **Autorización interna entre servicios:** si `sharing` o `itinerary` confiaran ciegamente en una
   cabecera interna en claro enviada desde el borde, cualquier compromiso lateral permitiría leer
   viajes ajenos (*confused deputy*).
3. **Blindaje estructural en redes sociales (`AMB-10`):** si la publicación filtrara «campos
   prohibidos» mediante una lista negra, agregar mañana un campo sensible nuevo al modelo canónico lo
   expondría accidentalmente en público.

## Drivers de decisión

* **QA-12** — rechazar el `100 %` de los intentos de acceso de usuarios no designados sin revelar
  siquiera si el viaje existe, caducidad por omisión a los `30 días` del fin del viaje y revocación
  efectiva en **`≤ 60 segundos`**.
* **QA-14** — registrar en bitácora de auditoría todos los accesos concedidos y denegados sobre viajes
  compartidos.
* **RF-11 / RF-13 / AMB-10** — compartición autenticada con designados y publicación voluntaria de
  resumen en redes sociales sin códigos de reserva, precios ni documentos.

## Opciones consideradas

* **B1** — Emitir un enlace secreto con token aleatorio (capacidad al portador) para designados que no
  tienen cuenta en Trotamundos.
* **B2** — Exigir al designado registrar una cuenta completa de viajero antes de poder visualizar el
  itinerario compartido.
* **B3** — Control de acceso por roles gruesos (RBAC) solo en `api-gateway`, propagando cabeceras sin
  firma interna y filtrando publicaciones por lista negra.
* **B4** — Autenticación OIDC en el borde + evaluación de políticas declarativas por atributos (ABAC)
  con vales firmados de corta vida + desafío OIDC sin contraseña (código OTP al correo designado) para
  invitados sin cuenta + proyección por lista blanca estricta (`ResumenPublicable`) para redes.

## Resultado de la decisión

Se adopta **B4**:

1. **Evaluación ABAC y vales criptográficos internos.** `api-gateway` verifica la firma y vigencia del
   JWT OIDC del solicitante; para recursos con reglas de propiedad o delegación (`viaje`, `reserva`,
   `comparticion`), `motor-autorizacion-abac` en `identity-access` evalúa políticas declarativas sobre
   atributos (`sujeto.usuario_id`, `sujeto.email_verificado`, `recurso.propietario_id`,
   `recurso.designados`, `recurso.expira_en`, `recurso.estado`) y emite un vale JWS de corta vida
   (`TTL 60 s`) ligado al recurso específico, verificado localmente por `sharing` e `itinerary`.
2. **Flujo sin cuenta para designados (`RF-11` / `QA-12`).** Si quien abre un enlace de compartición
   no posee sesión activa ni cuenta en Trotamundos, presenta su dirección de correo ante
   `autenticacion-oidc`. El servicio comprueba internamente si ese correo pertenece a `designados` de
   una compartición `Activa` y no vencida, mostrando siempre en pantalla el **mismo mensaje neutro**
   («Si tu dirección figura como autorizada, recibirás un código temporal») para impedir enumeración.
   Solo si coincide, envía un código de un solo uso de 6 dígitos (`TTL 10 min`, máx. `3` intentos) y,
   tras validarlo, emite un token OIDC efímero con alcance exclusivo `lectura:comparticion:{id}` sin
   crear perfil permanente ni retener datos más allá de la traza de auditoría (`CON-10`).
3. **Respuesta opaca uniforme, caducidad y revocación en `≤ 60 s`.** Toda petición cuyo sujeto no esté
   en `designados`, cuyo `comparticion_id` no exista, haya caducado (por omisión `fin_viaje + 30 días`)
   o haya sido revocado recibe idéntica respuesta **`404 Not Found`** de cuerpo genérico y deja
   registro auditable en `auditoria-y-revocacion`. Al revocar una compartición, `sharing` publica la
   invalidación inmediata en la caché regional (`< 5 s`) y el `TTL ≤ 60 s` de los vales garantiza
   corte efectivo en **`≤ 60 segundos`**.
4. **Proyección de lista blanca estricta para redes sociales (`RF-13`).** El módulo
   `publicacion-resumen` de `sharing` construye un tipo dedicado `ResumenPublicable` que **únicamente**
   admite cuatro atributos: `tituloViaje`, `ciudadesDestino[]`, `mesAnio` y `tiposTransporte[]`. Los
   localizadores PNR, números de vuelo/documento, importes, horarios exactos, direcciones de hotel y
   correos electrónicos son estructuralmente irrepresentables en ese contrato, y toda publicación
   requiere previsualización y confirmación explícita del viajero.

### Consecuencias

* **Bueno,** porque cumple sin excepciones el `100 %` de denegación a terceros de `QA-12` incluso si
  el enlace se reenvía en un grupo de mensajería, manteniendo baja la fricción para familiares sin
  cuenta.
* **Bueno,** porque erradica por construcción tanto el *confused deputy* interno como la fuga de
  localizadores PNR en redes sociales ante futuras extensiones del modelo canónico.
* **Malo,** porque introduce un paso de ingreso de código recibido por correo la primera vez que un
  designado sin cuenta abre el itinerario desde un navegador nuevo.

### Confirmación

* **Matriz automatizada de seguridad (`QA-12`):** pruebas de integración que ejercitan (a) designado
  con cuenta (`200`), (b) designado sin cuenta tras OTP válido (`200`), (c) usuario autenticado válido
  pero **no** designado (`404` idéntico a recurso inexistente), (d) compartición vencida a `+30 d`
  (`404`) y (e) acceso `5 s` después de revocar (`404`), verificando que los cinco eventos queden en
  `registro_auditoria`.
* **Prueba de contrato sobre `ResumenPublicable` (`AMB-10`):** prueba basada en propiedades que
  alimenta reservas completas con PNR, pasaporte, precios y domicilios y verifica que ningún valor ni
  subcadena sensible aparezca jamás en la carga saliente hacia `E-13`.

## Pros y contras de las opciones

### B1 — Enlace con token secreto para designados sin cuenta

* Bueno, porque abre el viaje en un clic sin verificar correo.
* **Malo, porque reenviar el enlace transfiere el acceso a terceros no designados, violando `QA-12` y
  contradiciendo `ADR-0007`.**

### B2 — Registro obligatorio de cuenta permanente para todo invitado

* Bueno, porque reutiliza únicamente el flujo de usuarios registrados.
* **Malo, porque degrada severamente la experiencia del destinatario ocasional y recolecta perfiles
  permanentes innecesarios (`CON-10`).**

### B3 — RBAC solo en el borde y filtrado de redes por lista negra

* Bueno, porque es simple de escribir inicialmente.
* **Malo, porque confía ciegamente en la red interna y cualquier atributo nuevo agregado a `Reserva`
  queda expuesto por omisión al publicar en redes.**

### B4 — OIDC + ABAC con vales firmados + OTP efímero para invitados + lista blanca

* Bueno, porque satisface simultáneamente `QA-12`, `QA-14`, `CON-10` y `AMB-10` con garantías
  verificables.
* Malo, porque requiere operar el envío transaccional del código OTP de acceso invitado.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D28](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d28--autorización-compartición-con-designados-con-y-sin-cuenta-y-publicación-segura-qa-12-rf-11-rf-13)
* Vistas afectadas: [vista-modulos-adaptadores](../04-vistas/vista-modulos-adaptadores.md), [vista-seguridad-y-datos](../04-vistas/vista-seguridad-y-datos.md)
* Relacionados: [ADR-0007](ADR-0007-identidad-y-comparticion.md), [ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md)
