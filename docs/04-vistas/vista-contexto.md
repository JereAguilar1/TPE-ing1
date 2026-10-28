# Vista de contexto

**Tipo:** el sistema como caja negra frente a su entorno.
**Responde:** ¿dónde empieza y termina el sistema? ¿con quién intercambia qué?

El diagrama y la tabla completa de las 16 interfaces externas están en el análisis inicial, porque
el contexto es una entrada del diseño y no un producto de él:

### → [1.2 Diagrama de contexto](../01-analisis-inicial/02-diagrama-de-contexto.md)

## Qué agrega la iteración 1 al contexto

La iteración 1 no cambió los límites del sistema, pero sí asignó **un componente responsable a cada
interfaz externa**. Esto es la regla de consistencia 4 de las vistas, y es lo que garantiza que no
quedó ninguna interfaz sin dueño.

| Interfaz externa | Componente responsable | Contrato |
|---|---|---|
| E-01 Viajero (web) | `edge` → `api-gateway` → `bff-web` | OpenAPI del BFF web |
| E-02 Viajero (móvil) | `edge` → `api-gateway` → `bff-mobile` | OpenAPI del BFF móvil |
| E-03 Persona designada | `api-gateway` → `sharing` | OpenAPI de compartición |
| E-04 Equipo de datos | `analytics-store` | SQL analítico |
| E-05 Proveedor de correo (con *push*) | `mail-ingest` + `identity-access` | Adaptador de proveedor de correo |
| E-06 Proveedor de correo (IMAP) | `mail-ingest` | Adaptador IMAP |
| E-07…E-10 Proveedores de viaje y GDS | `provider-sync` | Contrato canónico de adaptador |
| E-11 Trenes y autobuses | `provider-sync` — **punto de extensión** | Contrato canónico de adaptador |
| E-12 Agencia de viajes preferida | `support-liaison` | OpenAPI de la agencia |
| E-13 Redes sociales | `sharing` (operación `publicaciones`) | OAuth + API de la red |
| E-14 Proveedor de identidad | `identity-access` | OpenID Connect |
| E-15 Servicios de notificación push | `notification` | APNs / FCM |
| E-16 Mapas y geocodificación | `itinerary` | API del proveedor |

Ninguna interfaz externa queda sin componente responsable, y ningún componente atiende dos
interfaces con modelos de confianza distintos — salvo `sharing`, que atiende E-03 y E-13
deliberadamente con **dos operaciones separadas**, por
[AMB-10](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución).
