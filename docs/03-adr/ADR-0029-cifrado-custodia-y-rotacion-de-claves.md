---
estado: aceptado
fecha: 2026-10-29
decisores: Ivo Iriarte, Juan Emilio Pardo
consultados: Francisco Lozano, Jeremias Aguilar
informados: equipo completo
iteracion: 4
drivers: QA-13, CRN-05, CON-08, QA-14, RF-01
---

# ADR-0029: Cifrado por sobres con clave por usuario, custodia mTLS exclusiva, detección de anomalías y revocación regional en bloque

## Contexto y planteo del problema

A escala nominal, Trotamundos custodia el acceso delegado a **`9 millones` de buzones de correo**
(`15 M` de usuarios × `60 %` con correo conectado, `S-01`). Por eso **`QA-13` (`ASR-5`)** parte de una
hipótesis de brecha asumida: un atacante **ya logró comprometer otro servicio interno** (por ejemplo,
un contenedor de `booking-extraction` o `itinerary`) e intenta extraer tokens OAuth de refresco para
leer correos de usuarios.

Frente a ese escenario, la arquitectura debe garantizar simultáneamente cuatro propiedades medibles:
(1) que ningún servicio distinto de `identity-access` pueda leer ni descifrar los tokens almacenados,
(2) auditar el `100 %` de las emisiones de tokens de acceso, (3) detectar y cortar cualquier patrón de
extracción masiva en **`≤ 5 minutos`**, y (4) rotar claves periódicamente sin inactividad (`CRN-05`) y
ejecutar una revocación en bloque del `100 %` de los tokens de una región afectada en **`≤ 15
minutos`**.

## Drivers de decisión

* **QA-13 *(ASR-5)*** — aislamiento criptográfico ante compromiso de otro servicio interno, auditoría
  del `100 %`, detección de extracción masiva en `≤ 5 min` y revocación regional en bloque en `≤ 15
  min`.
* **CRN-05** — custodia segura, principio de privilegio mínimo y rotación periódica de claves y
  secretos sin ventana de caída.
* **QA-14 ([ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md))** — habilitar la destrucción criptográfica instantánea de los datos de un usuario individual al ejercer su derecho de supresión.
* **CON-08 / RF-01** — resguardo y revocabilidad inmediata del consentimiento sobre cuentas de correo.

## Opciones consideradas

* **C1** — Clave simétrica única por entorno inyectada mediante variables de configuración a los
  servicios que la necesiten.
* **C2** — Cifrado directo contra el HSM/KMS en cada lectura y escritura sin claves intermedias por
  usuario.
* **C3** — Cifrado por sobres (*envelope encryption*) con clave maestra regional (`KEK_region`) en
  HSM/KMS y clave de datos única por usuario (`DEK_u`), identidad de carga mTLS/SPIFFE exclusiva para
  `identity-access`, detección de anomalía en tiempo real (`≤ 2 min`) y revocación regional en dos
  fases (`≤ 12 min`).

## Resultado de la decisión

Se adopta **C3**:

1. **Jerarquía de cifrado por sobres (*Envelope Encryption*).**
   * Cada región posee una clave maestra **`KEK_region`** generada y confinada dentro del HSM/KMS
     regional (`VAULT`), cuyo material criptográfico jamás abandona el módulo hardware.
   * Cada usuario `u` recibe al registrarse una clave simétrica única **`DEK_u`** (`AES-256-GCM`), que
     se almacena únicamente envuelta (*wrapped*) por `KEK_region` junto con su `key_version`.
   * Todos los *refresh tokens* OAuth, credenciales delegadas de proveedores y sobres de respaldo de
     `u` se cifran con `DEK_u` vinculando `{ usuario_id, proposito, key_version }` como datos
     autenticados adicionales (*AAD*), impidiendo trasplantar un texto cifrado entre cuentas.
2. **Frontera criptográfica estricta (`Regla R5`) y entrega de tokens efímeros.** La política del KMS
   regional autoriza la operación `Decrypt` **exclusivamente** a la identidad criptográfica mTLS/SPIFFE
   del módulo `custodia-boveda` dentro de `identity-access`. Aunque un atacante comprometa `mail-ingest`
   y vuelque incluso la tabla cifrada de credenciales, carece de permiso sobre `KEK_region`. Para
   descargar correo, `mail-ingest` solicita por mTLS a `identity-access` un *access token* OAuth de
   alcance mínimo (`readonly`) y vida corta (**`TTL ≤ 15 min`**), que `mail-ingest` mantiene solo en
   memoria volátil y solo para buzones de los *buckets* cuyo arrendamiento posee ([ADR-0018](ADR-0018-consistencia-datos-multirregion.md)).
3. **Rotación periódica sin corte (`CRN-05`).** `KEK_region` rota automáticamente cada **`90 días`**
   creando una versión `v{N+1}` para todas las escrituras nuevas mientras `v{N}` permanece habilitada
   para lectura; un trabajador en segundo plano re-envuelve las claves `DEK_u` (sin tocar los datos
   masivos cifrados con ellas) y retira `v{N}` con **`0 s` de inactividad**.
4. **Auditoría del `100 %`, detección en `≤ 5 min` y revocación regional en `≤ 15 min`.**
   * Toda solicitud de desenvolvimiento o emisión de token escribe de forma síncrona en
     `auditoria-y-revocacion`.
   * Un detector en ventana deslizante de `60 s` evalúa por instancia solicitante dos reglas: (a) tasa
     de tokens pedidos `> 3×` el p99 histórico de una réplica de `mail-ingest`, o (b) solicitud sobre
     un `usuario_id` ajeno a las particiones arrendadas por esa réplica. Al dispararse, **revoca el
     certificado mTLS de la instancia sospechosa y congela emisiones en `≤ 2 minutos`** (cumpliendo
     con margen el tope de `≤ 5 min`).
   * Ante compromiso regional confirmado, el procedimiento automatizado de emergencia ejecuta dos
     fases: en **`t ≤ 30 s`** deshabilita la versión afectada de `KEK_region` en el KMS regional
     (dejando ilegible al instante el `100 %` de los tokens en reposo dentro del sistema), y entre
     **`t = 30 s` y `t ≤ 12 min`** lanza trabajadores paralelos por los `64` *buckets* regionales que
     revocan los *grants* OAuth ante los proveedores de correo (`E-05`) y transicionan los buzones a
     `RequiereReautorizacion`, cerrando debajo del límite de **`15 minutos`**.

### Consecuencias

* **Bueno,** porque limita el radio de explosión de cualquier vulnerabilidad en los otros 12 servicios:
  ningún proceso fuera de `identity-access` toca jamás un *refresh token* ni una clave `DEK_u`.
* **Bueno,** porque `DEK_u` por usuario destraba simultáneamente la cripto-supresión instantánea
  ([ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md)) y el registro testigo cifrado
  jurisdiccional ([ADR-0031](ADR-0031-residencia-de-datos-por-region.md)) manteniendo bajo el costo de
  llamadas al KMS.
* **Malo,** porque convierte a `identity-access` y al KMS regional en dependencias críticas del camino
  de descarga de correo (mitigado desplegándolos en las 3 zonas de disponibilidad de cada región,
  [vista-despliegue-nivel-2](../04-vistas/vista-despliegue-nivel-2.md)).

### Confirmación

* **Verificación estática y de políticas IAM/mTLS:** regla en CI que falla si cualquier módulo fuera de
  `identity-access` importa clientes de `VAULT`/KMS (`Regla R5`), más prueba de integración donde una
  identidad de servicio de `mail-ingest` intenta invocar `Decrypt` directamente o pedir un token de un
  *bucket* no arrendado y recibe `403 Forbidden` con alerta inmediata.
* **Simulacro de extracción y revocación (`QA-13`):** prueba automatizada que inyecta una ráfaga
  anómala de peticiones desde una réplica simulada de `mail-ingest` y verifica que el bloqueo se active
  en `< 5 min` y el barrido de revocación complete el lote escalado dentro del presupuesto de `< 15
  min`.

## Pros y contras de las opciones

### C1 — Clave simétrica única en configuración

* Bueno, porque no requiere infraestructura KMS.
* **Malo, porque un único volcado de memoria o configuración compromete los 9 millones de buzones e
  impide rotar sin corte.**

### C2 — Cifrado directo en KMS por cada operación sin `DEK_u`

* Bueno, porque centraliza todo en el HSM.
* **Malo, porque agota cuotas y encarece llamadas KMS a escala de millones de reconciliaciones, y no
  provee clave individual por usuario para supresión criptográfica.**

### C3 — Cifrado por sobres (`KEK_region` + `DEK_u`) + mTLS exclusivo + detección y revocación en dos fases

* Bueno, porque combina aislamiento criptográfico fuerte, rotación sin caída, bajo costo operativo y
  soporte nativo a privacidad por usuario.
* Malo, porque requiere gestionar el ciclo de vida de sobres `DEK_u` y certificados internos mTLS.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D29](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d29--cifrado-por-sobres-custodia-detección-anómala-y-revocación-de-claves-qa-13-crn-05)
* Vista afectada: [vista-seguridad-y-datos](../04-vistas/vista-seguridad-y-datos.md)
* Relacionados: [ADR-0007](ADR-0007-identidad-y-comparticion.md), [ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md), [ADR-0031](ADR-0031-residencia-de-datos-por-region.md)
