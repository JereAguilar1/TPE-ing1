// Interfaz web mínima del prototipo (paso 20, RF-09): el panel y el chat del asistente.
//
// Habla solo con `bff-web` (contratos/openapi/bff-web.yaml), salvo el inicio de sesión, que es de
// `identity-access`; nginx enruta las dos desde el mismo origen (`/api/bff`, `/api/ia/sesiones`).
// Los textos salen de `locales/es-AR.json` (ADR-0032) y cada tramo se presenta con el descriptor de
// su tipo (`GET /tipos-de-segmento`): este archivo no nombra ningún tipo de segmento (QA-15).
"use strict";

const BFF = "/api/bff";
const INICIO_DE_SESION = "/api/ia/sesiones";
const TIPO_DE_MEDIO = "application/vnd.trotamundos.v1+json";
const IDIOMA = "es-AR";
const ACTUALIZAR_CADA_MS = 15000;

const estado = {
  textos: {},
  tipos: {},          // tipo -> {versión -> presentacion}
  token: null,
  correo: null,
  sesionAsistente: null,
  etagPanel: null,
  temporizador: null,
};

// --- utilidades ------------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

function elemento(etiqueta, clase, texto) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== undefined && texto !== null) nodo.textContent = texto;
  return nodo;
}

/** Texto del catálogo, con el subconjunto de ICU MessageFormat que usa: `{x}` y plurales. */
function t(clave, argumentos = {}) {
  let valor = clave.split(".").reduce((nodo, parte) => (nodo ? nodo[parte] : undefined),
                                      estado.textos);
  if (typeof valor !== "string") return valor ?? clave;
  valor = valor.replace(/\{(\w+), plural, one \{([^{}]*)\} other \{([^{}]*)\}\}/g,
    (_, nombre, uno, otros) => (argumentos[nombre] === 1 ? uno : otros)
      .replace("#", String(argumentos[nombre])));
  return valor.replace(/\{(\w+)\}/g, (_, nombre) => String(argumentos[nombre] ?? ""));
}

/** Un UUID v4. `crypto.randomUUID` solo existe en contextos seguros; desde el celular por la red
    local la página es http, así que se arma con `getRandomValues`. */
function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// Lo único que se guarda en el navegador son valores que entregó el servidor, y solo si tienen su
// formato: el token de sesión (JWT) y el id de la sesión del asistente (UUID). Lo que escribe el
// viajero (su correo) no se guarda.
const FORMATOS = {
  token: /^[\w-]+\.[\w-]+\.[\w-]+$/,
  sesionAsistente: /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
};
const valido = (clave, valor) => typeof valor === "string" && FORMATOS[clave].test(valor);

const guardado = {
  leer(clave) {
    try {
      const valor = sessionStorage.getItem(clave);
      return valido(clave, valor) ? valor : null;
    } catch { return null; }
  },
  escribir(clave, valor) {
    if (!valido(clave, valor)) return;
    try { sessionStorage.setItem(clave, valor); } catch { /* sin almacenamiento */ }
  },
  borrar() { try { sessionStorage.clear(); } catch { /* sin almacenamiento */ } },
};

/** Un id para una ruta de la API: solo si es un UUID, y codificado. */
function idDeRuta(id) {
  if (!valido("sesionAsistente", id)) throw new Error("id inválido");
  return encodeURIComponent(id);
}

/** Fecha y hora en la zona horaria del lugar (ADR-0032). */
function fechaLocal(instante, zona, conHora = true) {
  const opciones = { timeZone: zona, weekday: "short", day: "numeric", month: "numeric" };
  if (conHora) Object.assign(opciones, { hour: "2-digit", minute: "2-digit", hour12: false });
  return new Intl.DateTimeFormat(IDIOMA, opciones).format(new Date(instante));
}

const ciudad = (zona) => zona.split("/").pop().replaceAll("_", " ");

/** Hora local del navegador, en 24 h («19:25»). */
const hora = (instante) => new Intl.DateTimeFormat(IDIOMA, {
  hour: "2-digit", minute: "2-digit", hour12: false }).format(instante);

// --- llamadas a la API -----------------------------------------------------------------------

class ErrorDeApi extends Error {
  constructor(estadoHttp, cuerpo) {
    super((cuerpo && (cuerpo.detail || cuerpo.title)) || `HTTP ${estadoHttp}`);
    this.estadoHttp = estadoHttp;
  }
}

async function llamar(metodo, ruta, { cuerpo, clave, cabeceras = {} } = {}) {
  const pedido = { method: metodo, headers: { Accept: `${TIPO_DE_MEDIO}, application/json`, ...cabeceras } };
  if (estado.token) pedido.headers.Authorization = `Bearer ${estado.token}`;
  if (clave) pedido.headers["Idempotency-Key"] = clave;
  if (cuerpo !== undefined) {
    pedido.headers["Content-Type"] = TIPO_DE_MEDIO;
    pedido.body = JSON.stringify(cuerpo);
  }
  const respuesta = await fetch(`${BFF}${ruta}`, pedido);
  if (respuesta.status === 304) return { noCambio: true };
  const datos = respuesta.status === 204 ? null : await respuesta.json().catch(() => null);
  if (respuesta.status === 401) salir();
  if (!respuesta.ok) throw new ErrorDeApi(respuesta.status, datos);
  return { datos, etag: respuesta.headers.get("ETag") };
}

// --- sesión ----------------------------------------------------------------------------------

async function ingresar(evento) {
  evento.preventDefault();
  $("error-ingreso").hidden = true;
  const correo = $("correo").value.trim();
  try {
    const respuesta = await fetch(INICIO_DE_SESION, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // OIDC simulado del prototipo: el «código» identifica al usuario (ADR-0007).
      body: JSON.stringify({ codigo: `oidc:${correo}:AM`, verificadorPkce: uuid() + uuid(),
                             uriRedireccion: `${location.origin}/` }),
    });
    if (!respuesta.ok) throw new Error(String(respuesta.status));
    const sesion = await respuesta.json();
    estado.token = sesion.tokenAcceso;
    estado.correo = correo;
    guardado.escribir("token", estado.token);
    await entrar();
  } catch {
    $("error-ingreso").textContent = t("ingresar.error");
    $("error-ingreso").hidden = false;
  }
}

function salir() {
  clearInterval(estado.temporizador);
  Object.assign(estado, { token: null, correo: null, sesionAsistente: null, etagPanel: null });
  guardado.borrar();
  $("aplicacion").hidden = true;
  $("cuenta").hidden = true;
  $("ingreso").hidden = false;
  $("mensajes").replaceChildren();
}

async function entrar() {
  $("ingreso").hidden = true;
  $("aplicacion").hidden = false;
  $("cuenta").hidden = false;
  $("correo-actual").textContent = estado.correo || "";
  await actualizarPanel();
  await abrirAsistente();
  clearInterval(estado.temporizador);
  estado.temporizador = setInterval(() => { void actualizarPanel(); }, ACTUALIZAR_CADA_MS);
}

// --- panel -----------------------------------------------------------------------------------

async function cargarTipos() {
  const { datos } = await llamar("GET", "/tipos-de-segmento");
  for (const descriptor of datos) {
    (estado.tipos[descriptor.tipo] ??= {})[descriptor.version] = descriptor.presentacion;
  }
}

function presentacion(segmento) {
  const versiones = estado.tipos[segmento.tipo] || {};
  return versiones[segmento.versionTipo]
    || versiones[Math.max(0, ...Object.keys(versiones).map(Number))]
    || { icono: "otro", titulo: "{operador} {referencia}", filas: [] };
}

async function actualizarPanel() {
  $("error-panel").hidden = true;
  try {
    const cabeceras = estado.etagPanel ? { "If-None-Match": estado.etagPanel } : {};
    const resultado = await llamar("GET", "/panel", { cabeceras });
    $("actualizado").textContent = t("panel.actualizado", { hora: hora(new Date()) });
    if (resultado.noCambio) return;
    estado.etagPanel = resultado.etag;
    dibujarPanel(resultado.datos);
  } catch (error) {
    if (error instanceof ErrorDeApi && error.estadoHttp === 401) return;
    $("error-panel").textContent = t("panel.error");
    $("error-panel").hidden = false;
  }
}

function dibujarTramo(segmento) {
  const vista = presentacion(segmento);
  const iconos = t("iconos");
  const tramo = elemento("li", "tramo");
  tramo.append(elemento("span", "icono", iconos[vista.icono] || iconos.otro));

  const cuerpo = elemento("div");
  const titulo = vista.titulo.replace(/\{(\w+)\}/g, (_, campo) => segmento[campo] ?? "").trim();
  const encabezado = elemento("div", "titulo" + (segmento.estado === "cancelado" ? " cancelado" : ""),
                              titulo);
  const marca = t(`estadosDeTramo.${segmento.estado}`);
  if (typeof marca === "string" && marca && marca !== `estadosDeTramo.${segmento.estado}`) {
    encabezado.append(" ", elemento("span", "etiqueta aviso", marca));
  }
  cuerpo.append(encabezado);

  const inicio = segmento.inicio;
  const conHora = inicio.precision === "instante";
  const cuando = conHora
    ? `${fechaLocal(inicio.instante, inicio.zonaHoraria)} (${t("panel.horaLocal", { ciudad: ciudad(inicio.zonaHoraria) })})`
    : `${fechaLocal(inicio.instante, inicio.zonaHoraria, false)} (${t("panel.todoElDia")})`;
  const lugares = inicio.lugar.nombre === segmento.fin.lugar.nombre
    ? inicio.lugar.nombre : `${inicio.lugar.nombre} → ${segmento.fin.lugar.nombre}`;
  cuerpo.append(elemento("div", null, lugares), elemento("div", "sutil", cuando));

  const filas = elemento("div", "filas sutil");
  for (const campo of vista.filas || []) {
    const valor = (segmento.detalle || {})[campo];
    if (valor !== undefined) filas.append(elemento("span", null, `${t("campos")[campo] || campo}: ${valor}`));
  }
  if (filas.childElementCount) cuerpo.append(filas);
  tramo.append(cuerpo);
  return tramo;
}

function tramosOrdenados(reservas) {
  return reservas.flatMap((r) => r.segmentos)
    .sort((a, b) => a.inicio.instante.localeCompare(b.inicio.instante));
}

function dibujarPanel(panel) {
  const viajes = $("viajes");
  viajes.replaceChildren();
  if (!panel.viajesActivos.length) viajes.append(elemento("p", "sutil", t("panel.sinViajes")));

  for (const viaje of panel.viajesActivos) {
    const bloque = elemento("article", "viaje");
    const encabezado = elemento("div", "viaje-encabezado");
    encabezado.append(elemento("h3", null, viaje.titulo),
                      elemento("span", "etiqueta", t(`estadosDeViaje.${viaje.estado}`)));
    bloque.append(encabezado);

    const zona = viaje.reservas[0]?.segmentos[0]?.inicio.zonaHoraria || "UTC";
    const conflictos = viaje.reservas.reduce((n, r) => n + (r.conflictosAbiertos || []).length, 0);
    const resumen = elemento("p", "sutil", `${t("panel.desdeHasta", {
      desde: fechaLocal(viaje.desde, zona, false), hasta: fechaLocal(viaje.hasta, zona, false) })} · ${
      t("panel.reservas", { cantidad: viaje.reservas.length })}`);
    if (conflictos) resumen.append(" ", elemento("span", "etiqueta aviso",
                                                 t("panel.conflictos", { cantidad: conflictos })));
    bloque.append(resumen);

    const lista = elemento("ul", "tramos");
    for (const segmento of tramosOrdenados(viaje.reservas)) lista.append(dibujarTramo(segmento));
    bloque.append(lista);
    viajes.append(bloque);
  }

  const porConfirmar = $("por-confirmar");
  porConfirmar.replaceChildren();
  if (panel.porConfirmar.length) {
    const seccion = elemento("div", "seccion-por-confirmar");
    seccion.append(elemento("h3", null, t("panel.porConfirmar")),
                   elemento("p", "sutil", t("panel.porConfirmarAyuda")));
    const lista = elemento("ul", "tramos");
    for (const segmento of tramosOrdenados(panel.porConfirmar)) lista.append(dibujarTramo(segmento));
    seccion.append(lista);
    porConfirmar.append(seccion);
  }
}

// --- asistente -------------------------------------------------------------------------------

function burbuja(autor, texto, clase = "") {
  const nodo = elemento("div", `burbuja ${autor} ${clase}`.trim(), texto);
  $("mensajes").append(nodo);
  $("mensajes").scrollTop = $("mensajes").scrollHeight;
  return nodo;
}

async function abrirAsistente() {
  const guardada = guardado.leer("sesionAsistente");
  if (guardada) {
    try {
      const { datos } = await llamar("GET", `/asistente/sesiones/${idDeRuta(guardada)}`);
      estado.sesionAsistente = guardada;
      $("mensajes").replaceChildren();
      for (const turno of datos.turnos) burbuja(turno.autor, turno.texto);
      if (datos.accionPendiente) mostrarPropuesta(datos.accionPendiente);
      return;
    } catch { /* venció o no es del usuario: se abre otra */ }
  }
  try {
    const { datos } = await llamar("POST", "/asistente/sesiones", { cuerpo: {}, clave: uuid() });
    estado.sesionAsistente = datos.id;
    guardado.escribir("sesionAsistente", datos.id);
    $("mensajes").replaceChildren();
    for (const turno of datos.turnos) burbuja(turno.autor, turno.texto);
  } catch {
    burbuja("asistente", t("asistente.error"));
  }
}

function mostrarPropuesta(propuesta) {
  const caja = elemento("div", "propuesta");
  const confirmar = elemento("button", null, t("asistente.confirmar"));
  const rechazar = elemento("button", "secundario", t("asistente.rechazar"));
  const vence = hora(new Date(propuesta.venceEn));
  const decidir = (decision) => {
    confirmar.disabled = rechazar.disabled = true;
    void enviar({ confirmacion: { accionId: propuesta.id, decision } },
                t(decision === "confirmar" ? "asistente.confirmo" : "asistente.rechazo"));
  };
  confirmar.addEventListener("click", () => decidir("confirmar"));
  rechazar.addEventListener("click", () => decidir("rechazar"));
  caja.append(confirmar, rechazar, elemento("span", "sutil", t("asistente.vence", { hora: vence })));
  $("mensajes").append(caja);
  $("mensajes").scrollTop = $("mensajes").scrollHeight;
}

async function enviar(cuerpo, textoDelViajero) {
  burbuja("viajero", textoDelViajero);
  try {
    const { datos } = await llamar("POST", `/asistente/sesiones/${idDeRuta(estado.sesionAsistente)}/mensajes`,
                                   { cuerpo, clave: uuid() });
    datos.mensajes.forEach((texto, i) => burbuja(
      "asistente", texto, datos.accionRealizada && i === 0 ? "realizada" : ""));
    if (datos.accionPropuesta) mostrarPropuesta(datos.accionPropuesta);
    if (datos.accionRealizada) {
      estado.etagPanel = null;
      await actualizarPanel();
    }
  } catch (error) {
    burbuja("asistente", error instanceof ErrorDeApi && error.estadoHttp === 409
      ? error.message : t("asistente.error"));
  }
}

async function enviarTexto(evento) {
  evento.preventDefault();
  const texto = $("texto").value.trim();
  if (!texto) return;
  $("texto").value = "";
  await enviar({ texto }, texto);
}

// --- arranque --------------------------------------------------------------------------------

async function iniciar() {
  estado.textos = await (await fetch(`locales/${IDIOMA}.json`)).json();
  for (const nodo of document.querySelectorAll("[data-texto]")) nodo.textContent = t(nodo.dataset.texto);
  $("texto").placeholder = t("asistente.placeholder");
  for (const sugerencia of t("asistente.sugerencias")) {
    const boton = elemento("button", "secundario", sugerencia);
    boton.addEventListener("click", () => { void enviar({ texto: sugerencia }, sugerencia); });
    $("sugerencias").append(boton);
  }
  $("form-ingreso").addEventListener("submit", (evento) => { void ingresar(evento); });
  $("form-chat").addEventListener("submit", (evento) => { void enviarTexto(evento); });
  $("salir").addEventListener("click", salir);
  $("actualizar").addEventListener("click", () => { estado.etagPanel = null; void actualizarPanel(); });

  await cargarTipos().catch(() => { /* sin catálogo, los tramos se ven con la presentación genérica */ });
  estado.token = guardado.leer("token");
  if (estado.token) await entrar(); else $("ingreso").hidden = false;
}

iniciar().catch(() => { $("ingreso").hidden = false; });
