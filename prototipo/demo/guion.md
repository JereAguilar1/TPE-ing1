# Guion de demostración (borrador)

Para la defensa de la 2da entrega. **Borrador**: se ajusta y se ensaya en el cierre (paso 21, lunes 23).
Duración objetivo: unos 15 minutos de demostración, más preguntas.

La idea que guía todo: el prototipo no busca las cifras de producción, sino **mostrar que los
mecanismos de la arquitectura funcionan** (ADR-0034). Cada momento dice qué decisión se ve en acción.

## Antes de empezar (10 minutos antes)

```bash
cd prototipo
make infra-arriba
make servicios-arriba          # los 11 contenedores, sanos
.venv/bin/python demo/cargar_viajes.py ana@ejemplo.com
```

- Abrir **http://localhost:18111** e ingresar con `ana@ejemplo.com`: el panel ya tiene un viaje.
- Tener abiertas en otras pestañas: el repositorio en GitHub (pestaña **Actions**, última corrida
  en verde), `prototipo/README.md` en la «Matriz código ↔ ADR» y una terminal en `prototipo/`.
- Opcional: el celular en la misma red, con `http://<IP de la computadora>:18111`.

**Si algo falla en vivo:** `bash demo/demo.sh` hace el mismo recorrido completo por terminal, y las
mediciones de los escenarios están en el registro de la integración continua (paso 6).

## 1. El panel: un único punto de verdad (2 min)

- Mostrar el panel: el viaje a Mendoza con la **ida que llegó por correo**, el **hotel cargado a
  mano** y la **vuelta por confirmar**, todo agrupado en un solo viaje; el tren a Barcelona aparte.
- Qué decir: las reservas llegan por tres caminos (correo, proveedor y carga manual) y se fusionan
  en un modelo canónico (ADR-0010, ADR-0013). La vuelta llegó con datos dudosos y no entra al
  viaje hasta que el viajero la confirme (bandas de confianza, ADR-0015, ASR-4).
- Mostrarla en el celular, si está: la misma página se adapta (el móvil nativo está diseñado,
  ADR-0005 y ADR-0033, y no construido por el recorte).

## 2. Una actualización llega sola en segundos — ASR-1 / QA-01 (3 min)

- En la terminal, que la aerolínea cambie el horario de la ida (ver «Comandos de apoyo») y volver a
  la página: el panel lo muestra solo en menos de 15 s (la página relee el panel cada 15 s; el
  sistema lo tiene en menos de un segundo).
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
4. (Con la disrupción publicada, ver «Comandos de apoyo») «¿Se canceló mi vuelo?» → avisa la
   cancelación y propone pasarle el caso a la agencia → **Confirmar** → caso derivado (ADR-0039).
5. «¿Mi agencia ya recibió el caso?» → indica dónde seguirlo, sin abrir otro.

Qué decir: el asistente entiende por reglas detrás de un intérprete intercambiable; un modelo de
lenguaje se enchufa sin tocar el resto (ADR-0037). No agrega interfaces al núcleo: usa las que ya
existían, como preveía el punto de extensión de la iteración 4 (ADR-0034, CON-06).

## 4. Pico de disrupción sin pérdidas — ASR-2 / QA-04 (2 min)

- Mostrar en GitHub la salida del escenario de QA-04: 200 correos (cada uno dos veces) y 200
  avisos del proveedor en desorden, mientras 6 lectores consultan el panel: cero actualizaciones
  perdidas, ninguna duplicada, el aviso viejo no pisa al nuevo, y el panel con p95 ≈ 130 ms
  (el objetivo con sobrecarga es ≤ 1.500 ms).
- Qué decir: es a escala de prototipo; el escalado y las 9.000 peticiones/s están diseñados
  (ADR-0020, ADR-0021) y no se buscan con Docker Compose.

## 5. Un medio de transporte nuevo sin tocar el dominio — QA-15 (2 min)

- Mostrar el tren en el panel: llegó por correo y lo leyó **su propio extractor**, un complemento.
- Mostrar que agregarlo fue: el descriptor `contratos/tipos-de-segmento/tren.v1.yaml`, el
  complemento `booking_extraction/complementos/boleto_tren_simulado.py` y una entrada en
  `comun/catalogo_extractores.yaml`. Ningún servicio de dominio cambió (ADR-0011, guía de
  extensión de la iteración 4); la regla la verifica `tests/test_arquitectura.py`.

## 6. Trazabilidad y especificaciones — QA-16 (2 min)

- Mostrar la «Matriz código ↔ ADR» del README: cada decisión con el código que la implementa y la
  prueba que la verifica.
- Mostrar un contrato (`contratos/openapi/bff-web.yaml`) y decir que las rutas de cada servicio se
  comparan contra su contrato, y que la página misma se prueba contra él (*spec-driven*, ADR-0009).
- Mostrar «Diseñado y no construido»: lo que el recorte dejó afuera está justificado, no es un
  faltante.

## Comandos de apoyo

Correr desde `prototipo/`, con el correo usado en la página (`CORREO=ana@ejemplo.com`):

- **Cambio de horario de la aerolínea (momento 2):** ver `notificar_cambio` en
  `tests/escenarios/contenedores.py`; el localizador de la ida es el que imprimió `cargar_viajes.py`.
- **Disrupción y agencia preferida (momento 3.4):** la etapa 7 de `demo/demo.sh` publica
  `PreferenciasActualizadas` y `DisrupcionDetectada` para el viajero.

> Pendiente para el cierre: dejar estos dos comandos como scripts de una línea en `demo/`, y
> repartir quién presenta cada momento.

## Preguntas que conviene tener preparadas

- **¿Por qué el asistente no usa IA?** El enunciado pide un bot de primer nivel, no IA. El
  intérprete es intercambiable: el modelo de lenguaje está diseñado como complemento (ADR-0037),
  con redacción de datos personales, y no se construyó para que el prototipo sea determinista y
  sin costo por mensaje.
- **¿Dónde está la multirregión (ASR-3)?** Construida en versión mínima (paso 16): dos regiones,
  AM y EU, cada una con su base, su `itinerary` y su `bff-web`; testigo síncrono de los comandos
  manuales y conmutación en `api-gateway` (ADR-0002, ADR-0018). El escenario de QA-05
  (`tests/escenarios/test_qa05_perdida_de_region.py`, en el trabajo `servicios`) tira la región AM
  y mide: el viajero vuelve a tener servicio desde EU en unos 7 s, con lo confirmado intacto.
  La página web no conmuta (habla con el `bff-web` de AM por nginx): QA-05 se muestra con el
  escenario o por `api-gateway`. La tercera región y la replicación de lo ingerido, en
  «Diseñado y no construido».
- **¿Y la app móvil?** Diseñada (ADR-0005, ADR-0019, ADR-0033); la página web se adapta al celular.
- **¿Cómo saben que el código respeta la arquitectura?** Reglas en `tests/test_arquitectura.py`
  (ningún servicio importa a otro, dependencias internas por vista de módulos, ningún tipo de
  segmento nombrado en el dominio) y contratos validados en ejecución.
- **¿Qué cambió respecto de la 1ra entrega?** Iteración 5 de ADD para la Opción B, ADR-0037 a
  ADR-0041 (sin editar los aceptados: ADR-0040 y ADR-0041 precisan a ADR-0034 y ADR-0035).
