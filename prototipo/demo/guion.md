# Guion de demostración

Para la defensa de la 2da entrega. Duración objetivo: unos 18 minutos de demostración, más
preguntas.

La idea que guía todo: el prototipo no busca las cifras de producción, sino **mostrar que los
mecanismos de la arquitectura funcionan** (ADR-0034). Cada momento dice qué decisión se ve en acción.
Los cinco ASR (QA-01, QA-04, QA-05, QA-11 y QA-13) aparecen en los momentos 2, 4, 5 y 6.

## Antes de empezar (10 minutos antes)

```bash
cd prototipo
make infra-arriba
make servicios-arriba          # todos los contenedores, sanos (las dos regiones, AM y EU)
.venv/bin/python demo/cargar_viajes.py ana@ejemplo.com
```

- Abrir **http://localhost:18111** e ingresar con `ana@ejemplo.com`: el panel ya tiene un viaje.
- Tener abiertas en otras pestañas: el repositorio en GitHub (pestaña **Actions**, última corrida
  en verde, con el trabajo `servicios` abierto), `prototipo/docs/matriz-codigo-adr.md`
  y una terminal en `prototipo/`.
- Opcional: el celular en la misma red, con `http://<IP de la computadora>:18111`.

**Si algo falla en vivo:** `bash demo/demo.sh` hace el recorrido de los momentos 1 a 3 por terminal,
y las mediciones de los escenarios están en el registro del trabajo `servicios` de la integración
continua.

## Reparto

Lo completa el grupo antes del ensayo.

| Momento | Presenta |
|---|---|
| 1 y 2 | |
| 3 | |
| 4 y 5 | |
| 6, 7 y 8 | |

## 1. El panel: un único punto de verdad (2 min)

- Mostrar el panel: el viaje a Mendoza con la **ida que llegó por correo**, el **hotel cargado a
  mano** y la **vuelta por confirmar**, todo agrupado en un solo viaje; el tren a Barcelona aparte.
- Qué decir: las reservas llegan por tres caminos (correo, proveedor y carga manual) y se fusionan
  en un modelo canónico (ADR-0010, ADR-0013). La vuelta llegó con datos dudosos y no entra al
  viaje hasta que el viajero la confirme (bandas de confianza, ADR-0015).
- Mostrarla en el celular, si está: la misma página se adapta (el móvil nativo está diseñado,
  ADR-0005 y ADR-0033, y no construido por el recorte).

## 2. Una actualización llega sola en segundos — ASR-1 / QA-01 (3 min)

- En la terminal: `.venv/bin/python demo/apoyo.py cambio-de-horario ana@ejemplo.com`. La
  aerolínea avisa que la ida sale una hora y media más tarde. Volver a la página: el panel lo
  muestra solo en menos de 15 s (la página relee el panel cada 15 s; el sistema lo tiene en menos
  de un segundo).
- Qué decir: el camino es aviso del proveedor → `provider-sync` (capa de anticorrupción con el
  adaptador como complemento, ADR-0006) → evento por el *broker* con *outbox* y carriles por
  urgencia (ADR-0014, ADR-0020) → `itinerary` → panel. El requisito es ≤ 5 min.
- Mostrar en GitHub, en el trabajo `servicios`, la medición del escenario de QA-01: p95 por correo
  y por proveedor, y cada tramo contra su presupuesto.

## 3. El asistente virtual — Opción B (4 min)

En el chat de la página:

1. «¿Cómo viene mi viaje?» → responde con fechas en la hora del lugar.
2. «¿Tengo reservas por confirmar?» → «confirmala» → **Confirmar** → la vuelta entra al viaje.
   Qué decir: nada cambia sin confirmación explícita, y la propuesta vence (ADR-0038).
3. «me pasaron el vuelo a las 22:30» → muestra el cambio exacto antes de hacerlo → **Confirmar**.
4. En la terminal: `.venv/bin/python demo/apoyo.py disrupcion ana@ejemplo.com` (el viajero elige
   su agencia en `preferences` y la aerolínea cancela el vuelo). En el chat: «¿Se canceló mi
   vuelo?» → avisa la cancelación y propone pasarle el caso a la agencia → **Confirmar** → caso
   derivado a «Agencia del Sur» (ADR-0039).
5. «¿Mi agencia ya recibió el caso?» → indica dónde seguirlo, sin abrir otro.

Qué decir: el asistente entiende por reglas detrás de un intérprete intercambiable; un modelo de
lenguaje se enchufa sin tocar el resto (ADR-0037). No agrega interfaces al núcleo: usa las que ya
existían, como preveía el punto de extensión de la iteración 4 (ADR-0034, CON-06).

## 4. Pico de disrupción sin pérdidas — ASR-2 / QA-04 (1,5 min)

- Mostrar en GitHub la salida del escenario de QA-04: 200 reenvíos (100 reservas, cada correo dos veces) y 200
  avisos del proveedor en desorden, mientras 6 lectores consultan el panel: cero actualizaciones
  perdidas, ninguna duplicada, el aviso viejo no pisa al nuevo, y el panel con p95 ≈ 130 ms
  (el objetivo con sobrecarga es ≤ 1.500 ms).
- Qué decir: es a escala de prototipo; el escalado y las 9.000 peticiones/s están diseñados
  (ADR-0020, ADR-0021) y no se buscan con Docker Compose.

## 5. Se cae una región — ASR-3 / QA-05 (2 min)

- En la terminal:
  `TROTAMUNDOS_EXIGIR_CONTENEDORES=1 .venv/bin/python -m pytest -s tests/escenarios/test_qa05_perdida_de_region.py`
  (unos 30 s). Un viajero de AM confirma una reserva y una baja, y la región AM se cae de golpe
  (`docker compose kill`). Imprime en cuánto tiempo el viajero vuelve a tener servicio desde EU
  (unos 7 s; el requisito es ≤ 60 s) y verifica que lo confirmado está intacto, con los mismos
  ids, y que la página también conmuta. Al terminar levanta AM de nuevo.
- Qué decir: cada usuario tiene una región primaria y una de respaldo (ADR-0018). Antes de
  confirmar un comando manual, `itinerary` lo deja en el **registro testigo** de la región de
  respaldo: sin testigo no hay `201` (pérdida de datos confirmados = 0). `api-gateway` comprueba
  la salud de cada región cada 2 s y, con 3 fallos, manda a los usuarios a su región de respaldo,
  que reproduce el testigo antes de atenderlos (ADR-0002).
- No tirar AM a mano con el panel de `ana@ejemplo.com` abierto: lo que llegó por correo no se
  replica en EU (ver «Preguntas»), y la ida y la vuelta desaparecerían del panel.

## 6. Formato desconocido y custodia de credenciales — ASR-4 / QA-11 y ASR-5 / QA-13 (1,5 min)

- En la terminal (2 s):

  ```bash
  .venv/bin/python -m pytest -v \
    "tests/booking_extraction/test_servicio.py::test_desconocido_publica_una_salida_segura_y_deduplica_evento_y_correo" \
    "tests/test_arquitectura.py::test_regla_r5_solo_custodia_boveda_usa_cifrado_de_boveda" \
    "tests/identity_access/test_api_identity_access.py::test_ciclo_de_vida_buzones_boveda_y_token_efimero" \
    "tests/identity_access/test_api_identity_access.py::test_deteccion_anomala_y_revocacion_regional_en_bloque"
  ```

- Qué decir: un correo de formato desconocido no inventa una reserva: publica
  `ExtraccionNoReconocida` con una huella sin contenido (ADR-0035, QA-11). Las credenciales de
  correo se cifran por sobres (`KEK_region` / `DEK_u`), solo `custodia_boveda` toca el cifrado
  (regla R5, verificada sobre todo el código), los tokens son efímeros y una anomalía revoca la
  región en bloque (ADR-0029, QA-13).

## 7. Un medio de transporte nuevo sin tocar el dominio — QA-15 (1,5 min)

- Mostrar el tren en el panel: llegó por correo y lo leyó **su propio extractor**, un complemento.
- Mostrar que agregarlo fue: el descriptor `contratos/tipos-de-segmento/tren.v1.yaml`, el
  complemento `booking_extraction/complementos/boleto_tren_simulado.py` y una entrada en
  `comun/catalogo_extractores.yaml`. Ningún servicio de dominio cambió (ADR-0011, guía de
  extensión de la iteración 4); la regla la verifica `tests/test_arquitectura.py`.

## 8. Trazabilidad y especificaciones — QA-16 (2 min)

- Mostrar la matriz código ↔ ADR (`docs/matriz-codigo-adr.md`): cada decisión con el código que la implementa y la
  prueba que la verifica, y el estado de los ADR (`docs/estado-de-los-adr.md`): qué parte de cada ADR
  está en código.
- Mostrar un contrato (`contratos/openapi/bff-web.yaml`) y decir que cada servicio se prueba contra
  su contrato con pedidos generados (Schemathesis, `tests/contratos_api/`), y que la página misma
  usa solo sus operaciones (*spec-driven*, ADR-0009, ADR-0017).
- Mostrar `docs/disenado-y-no-construido.md`: lo que el recorte dejó afuera está justificado, no es un
  faltante.

## Comandos de apoyo

Desde `prototipo/`, con el correo usado en la página:

| Para | Comando |
|---|---|
| Cargar los viajes de ejemplo | `.venv/bin/python demo/cargar_viajes.py ana@ejemplo.com` |
| Cambio de horario de la aerolínea (momento 2) | `.venv/bin/python demo/apoyo.py cambio-de-horario ana@ejemplo.com` |
| Agencia preferida y cancelación del vuelo (momento 3.4) | `.venv/bin/python demo/apoyo.py disrupcion ana@ejemplo.com` |
| Pérdida de la región AM (momento 5) | `TROTAMUNDOS_EXIGIR_CONTENEDORES=1 .venv/bin/python -m pytest -s tests/escenarios/test_qa05_perdida_de_region.py` |
| Recorrido completo por terminal (plan B) | `bash demo/demo.sh` |

Si se tira AM a mano (`docker compose kill itinerary-escritura itinerary-lectura bff-web`), para
volver: `docker compose up -d --wait itinerary-escritura itinerary-lectura bff-web && docker compose
restart api-gateway`. El *gateway* no devuelve solo el tráfico a una región que volvió (ADR-0018 §4).

## Preguntas que conviene tener preparadas

- **¿Por qué el asistente no usa IA?** El enunciado pide un bot de primer nivel, no IA. El
  intérprete es intercambiable: el modelo de lenguaje está diseñado como complemento (ADR-0037),
  con redacción de datos personales, y no se construyó para que el prototipo sea determinista y
  sin costo por mensaje.
- **¿Dónde está la multirregión (ASR-3)?** Construida en versión mínima (paso 16): dos regiones,
  AM y EU, cada una con su base, su `itinerary` y su `bff-web`; testigo síncrono de los comandos
  manuales y conmutación en `api-gateway` (ADR-0002, ADR-0018). La página también conmuta: nginx
  la manda por `api-gateway`. La tercera región y la replicación de lo ingerido, en «Diseñado y no
  construido».
- **¿Y lo que llegó por correo si cae AM?** No está en EU: el prototipo no construye la replicación
  asíncrona continua. ADR-0018 lo acepta para la ingesta automática porque la fuente conserva el
  mensaje y la reconciliación lo vuelve a traer de forma idempotente; el `RPO = 0` es para lo que el
  viajero confirmó a mano, pero el escenario del prototipo solo verifica altas y bajas de reservas creadas manualmente. Una confirmación o edición de una reserva ingerida necesita además replicar su estado previo; esa garantía completa queda sin construir.
- **¿Cómo se comparte un viaje (QA-12)?** `sharing` (paso 13): designados con cuenta e invitados con
  código de un solo uso, con la decisión ABAC en `identity-access` y un vale firmado de 60 s; todo
  acceso no permitido es el mismo `404` (ADR-0028).
- **¿Y la app móvil?** Diseñada (ADR-0005, ADR-0019, ADR-0033); `bff-mobile` está construido con
  su resumen de ≤ 15 KB, y la página web se adapta al celular.
- **¿Cómo saben que el código respeta la arquitectura?** Reglas en `tests/test_arquitectura.py`
  (ningún servicio importa a otro, dependencias internas por vista de módulos, ningún tipo de
  segmento nombrado en el dominio, R5) y contratos validados en ejecución y con Schemathesis.
- **¿Por qué tantas decisiones en 🟨?** El prototipo es una tajada vertical (ADR-0034, y el
  enunciado pide acotar el alcance): 🟨 quiere decir que el mecanismo está construido y probado,
  y cada fila dice qué parte no y dónde está justificada.
- **¿Qué cambió respecto de la 1ra entrega?** Iteración 5 de ADD para la Opción B, ADR-0037 a
  ADR-0041, y ADR-0042 al construir la supresión coordinada; ninguno edita un ADR aceptado
  (ADR-0040, ADR-0041 y ADR-0042 precisan a ADR-0034, ADR-0035 y ADR-0030).
