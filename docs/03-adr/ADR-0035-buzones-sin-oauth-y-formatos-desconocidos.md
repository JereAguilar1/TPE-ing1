---
estado: aceptado
fecha: 2026-10-29
decisores: Juan Emilio Pardo, Ivo Iriarte
consultados: Jeremias Aguilar, Francisco Lozano
informados: equipo completo
iteracion: 4
drivers: CON-08, QA-11, QA-13, RF-01, RF-03, RF-06, AMB-09
---

# ADR-0035: Ingesta de buzones sin OAuth mediante reenvío verificado o credenciales delegadas, y flujo asistido sin corrupción ante formatos desconocidos

## Contexto y planteo del problema

En el plano de obtención e interpretación de correo electrónico confluyen dos bordes arquitectónicos
que las iteraciones anteriores dejaron abiertos para cerrar en la iteración 4:

1. **Proveedores de correo sin OAuth 2.0 (`E-06`, asunto abierto de [ADR-0007](ADR-0007-identidad-y-comparticion.md)):**
   mientras Gmail y Microsoft 365 soportan delegación OAuth con alcance de solo lectura (`E-05`),
   numerosos servidores corporativos, universitarios o regionales solo hablan correo estándar / IMAP.
   Pedir y guardar la contraseña principal del correo del usuario violaría frontalmente **`CON-08`**
   («acceso seguro y autorizado») y multiplicaría la gravedad de cualquier incidente en **`QA-13`**;
   pero rechazar toda cuenta sin OAuth dejaría afuera una porción relevante de viajeros de negocios.
2. **Cierre hacia el usuario y aprendizaje ante formatos desconocidos (`QA-11` / `ASR-4` y riesgo
   `R-2`):** la iteración 2 definió el contrato del complemento `Extractor` y las tres bandas de
   confianza (`D15`), pero faltaba cerrar qué recibe exactamente el viajero cuando un correo legítimo
   de viaje no es reconocido por ningún extractor (`0 %` de inserción silenciosa de datos erróneos) y
   cómo detecta el equipo qué formatos nuevos priorizar (`≤ 16 h-p`) sin guardar cuerpos de correo con
   datos personales (`AMB-09`).

## Drivers de decisión

* **CON-08 / QA-13 / RF-01** — acceso explícitamente autorizado y revocable al correo del usuario,
  prohibiendo bajo cualquier circunstancia solicitar o almacenar su contraseña primaria.
* **QA-11 *(ASR-4)*** — `0 %` de reservas con datos corruptos insertadas silenciosamente ante un
  formato desconocido, notificación clara al usuario con opción de carga asistida e incorporación de un
  extractor nuevo en `≤ 16 horas-persona`.
* **RF-03 / RF-06 / AMB-09** — continuidad hacia la gestión manual asistida descartando siempre el
  cuerpo crudo del mensaje tras procesarlo.

## Opciones consideradas

* **K1** — Solicitar y almacenar cifrada la contraseña principal IMAP del usuario para servidores sin
  OAuth, y descartar en silencio los correos de formato no reconocido.
* **K2** — Soportar exclusivamente proveedores con OAuth 2.0 (Gmail/Microsoft), bloqueando el resto de
  cuentas de correo.
* **K3** — Prohibición absoluta de contraseñas primarias + buzón de reenvío dedicado por usuario
  autenticado con `DKIM/SPF/ARC` como vía universal sin OAuth + IMAP directo solo con `XOAUTH2` o
  contraseña de aplicación específica revocable + huella estructural sin PII y borrador asistido ante
  `ExtraccionNoReconocida`.

## Resultado de la decisión

Se adopta **K3**:

1. **Política innegociable sobre credenciales de correo (`CON-08`).** Trotamundos **jamás acepta,
   transmite ni almacena la contraseña primaria** de una cuenta de correo. Para usuarios cuyo proveedor
   no expone OAuth 2.0 estándar (`E-06`) se proveen dos mecanismos seguros:
   * **Vía universal primaria — Dirección de reenvío dedicada por usuario:** `mail-ingest` asigna un
     alias criptográficamente aleatorio `viajes+<token>@ingesta.trotamundos.app` asociado al
     `usuario_id`. El viajero reenvía confirmaciones puntuales o configura una regla automática de
     reenvío para remitentes de viaje en su propio servidor; al recibir un correo, `mail-ingest`
     verifica firmas `DKIM`/`SPF`/`ARC` y coincidencia con el remitente autorizado del usuario, y lo
     inyecta en `< 5 s` al mismo flujo `MensajeNormalizado → booking-extraction` (`QA-01`). **No
     requiere custodiar ninguna credencial** y se revoca en el acto regenerando o desactivando el alias.
   * **Vía complementaria — IMAPs restringido a credenciales delegadas:** solo se permite conexión
     `IMAPs` (`TLS 1.3`, con los límites de concurrencia y sondeo de [ADR-0024](ADR-0024-cortacircuitos-reintentos-y-cuotas.md))
     hacia dominios que soporten `XOAUTH2` o contraseñas de aplicación específicas y revocables
     distintas de la clave principal, custodiadas bajo el sobre `DEK_u`/`KEK_region` de
     [ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md).
2. **Flujo extremo a extremo ante formato desconocido o confianza `< 0,60` (`QA-11` / acotación de
   `R-2`):**
   * **Bloqueo total de escritura automática (`0 %` error silencioso):** si ningún complemento
     `Extractor` reconoce el mensaje, si la confianza cae debajo del umbral bajo (`0,60`) o si falla
     una invariante de `validador-canonico` (p. ej. fecha de llegada anterior a salida en UTC),
     `booking-extraction` **no emite `ReservaExtraida`**.
   * **Huella estructural anónima para evolucionar en `≤ 16 h-p`:** antes de descartar el cuerpo de
     memoria (`AMB-09`), `observabilidad-de-calidad` registra únicamente `(dominio_remitente,
     fingerprint_estructural)` —un *hash* sobre la jerarquía de etiquetas HTML/MIME y cabeceras sin
     ningún valor textual ni PII— incrementando una métrica en OpenTelemetry. Esto agrupa de inmediato
     las nuevas plantillas reales por volumen y genera el esqueleto declarativo para escribir y validar
     el nuevo complemento `Extractor` en `12–14 h-p` (`≤ 16 h-p`, ver [guias-de-extension.md](../02-proceso-add/iteracion-4/guias-de-extension.md)).
   * **Aviso y alta manual pre-rellenada al viajero:** se emite `ExtraccionNoReconocida` con metadatos
     seguros del sobre (remitente, asunto truncado, fecha de recepción y campos candidatos no validados
     marcados explícitamente como `borradorSugerido`); `notification` informa al usuario por canal
     administrativo y enlaza al formulario de `POST /reservas` (`RF-06`) pre-completado para que el
     viajero revise y confirme con un toque.

### Consecuencias

* **Bueno,** porque cierra el asunto pendiente de `ADR-0007` brindando cobertura al `100 %` de los
  proveedores de correo del mercado sin sacrificar `CON-08` ni agrandar el riesgo `QA-13`.
* **Bueno,** porque garantiza por construcción el `0 %` de corrupción silenciosa exigido por `QA-11` y
  convierte el riesgo `R-2` en un ciclo de mejora medible sin recolectar correos privados.
* **Malo,** porque en proveedores sin OAuth ni claves de aplicación el usuario debe crear una regla de
  reenvío en su cliente de correo (asistido con instrucciones paso a paso por proveedor).

### Confirmación

* **Prueba de conformidad de `QA-11`:** inyectar en `booking-extraction` lotes de correos con (a)
  plantillas inéditas, (b) plantillas conocidas alteradas con fechas incoherentes y (c) campos
  truncados, comprobando `0` emisiones de `ReservaExtraida`, `100 %` de emisión de
  `ExtraccionNoReconocida`, descarte del cuerpo crudo y ausencia total de PII en las métricas de
  `fingerprint_estructural`.
* **Prueba de seguridad del receptor de reenvío:** verificar que correos sin validación `DKIM/SPF` o
  desde remitentes no vinculados al alias del usuario sean rechazados en el borde de `mail-ingest` sin
  entrar al *broker*.

## Pros y contras de las opciones

### K1 — Guardar contraseña primaria IMAP y descartar silenciosamente formatos desconocidos

* Bueno, porque automatiza conexión directa con cualquier servidor IMAP antiguo.
* **Malo, porque viola `CON-08`, convierte la bóveda en un objetivo catastrófico y deja al viajero
  creyendo que su reserva fue cargada cuando en realidad se ignoró.**

### K2 — Restringir Trotamundos únicamente a cuentas Gmail y Microsoft 365

* Bueno, porque evita mantener caminos alternativos a OAuth.
* **Malo, porque excluye correos corporativos y proveedores regionales en nuevos mercados (`QA-18`).**

### K3 — Alias de reenvío verificado + IMAP solo delegado + huella anónima y alta asistida

* Bueno, porque preserva intactas `CON-08`, `QA-11`, `QA-13` y `AMB-09` con cobertura universal.
* Malo, porque añade el receptor SMTP entrante autenticado en `mail-ingest`.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D35](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d35--tratamiento-de-buzones-sin-oauth-y-flujo-ante-formatos-desconocidos-con-08-qa-11)
* Vistas afectadas: [vista-modulos-adaptadores](../04-vistas/vista-modulos-adaptadores.md), [vista-seguridad-y-datos](../04-vistas/vista-seguridad-y-datos.md)
* Relacionados: [ADR-0004](ADR-0004-obtencion-de-correo.md), [ADR-0006](ADR-0006-capa-de-anticorrupcion.md), [ADR-0007](ADR-0007-identidad-y-comparticion.md), [ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md)
