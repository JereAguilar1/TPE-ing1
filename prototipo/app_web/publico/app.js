// Interfaz web del prototipo (paso 20, RF-09): el panel, el detalle de cada viaje, los viajes
// anteriores, confirmar o descartar lo dudoso, resolver conflictos, la carga manual y el chat del
// asistente.
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
  esquemas: {},       // tipo -> esquemaDeDetalle de la versión vigente (para la carga manual)
  viajeActual: null,
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

async function llamar(metodo, ruta, { cuerpo, clave, cabeceras = {}, consulta } = {}) {
  const pedido = { method: metodo, headers: { Accept: `${TIPO_DE_MEDIO}, application/json`, ...cabeceras } };
  if (estado.token) pedido.headers.Authorization = `Bearer ${estado.token}`;
  if (clave) pedido.headers["Idempotency-Key"] = clave;
  if (cuerpo !== undefined) {
    pedido.headers["Content-Type"] = TIPO_DE_MEDIO;
    pedido.body = JSON.stringify(cuerpo);
  }
  const parametros = consulta ? `?${new URLSearchParams(consulta)}` : "";
  const respuesta = await fetch(`${BFF}${ruta}${parametros}`, pedido);
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
    const vigente = Math.max(0, ...Object.keys(estado.tipos[descriptor.tipo]).map(Number));
    if (descriptor.version === vigente) estado.esquemas[descriptor.tipo] = descriptor.esquemaDeDetalle;
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
    if (valor !== undefined) {
      filas.append(elemento("span", null, `${t("campos")[campo] || campo}: ${t("valores")[valor] || valor}`));
    }
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
    const titulo = elemento("h3");
    const enlace = elemento("button", "enlace", viaje.titulo);
    enlace.title = t("panel.verViaje");
    enlace.addEventListener("click", () => { void abrirViaje(viaje.id); });
    titulo.append(enlace);
    encabezado.append(titulo, elemento("span", "etiqueta", t(`estadosDeViaje.${viaje.estado}`)));
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
    for (const reserva of panel.porConfirmar) seccion.append(dibujarPorConfirmar(reserva));
    porConfirmar.append(seccion);
  }
}

function dibujarPorConfirmar(reserva) {
  const bloque = elemento("div", "reserva");
  const lista = elemento("ul", "tramos");
  for (const segmento of tramosOrdenados([reserva])) lista.append(dibujarTramo(segmento));
  const acciones = elemento("div", "acciones");
  const confirmar = elemento("button", null, t("porConfirmar.confirmar"));
  const descartar = elemento("button", "secundario", t("porConfirmar.descartar"));
  confirmar.addEventListener("click", () => { void decidirReserva(reserva.id, "confirmar"); });
  descartar.addEventListener("click", () => { void decidirReserva(reserva.id, "descartar"); });
  acciones.append(confirmar, descartar);
  bloque.append(lista, acciones);
  return bloque;
}

// --- acciones sobre reservas y viajes ---------------------------------------------------------

function avisar(texto, esError = false) {
  const aviso = $("aviso");
  aviso.textContent = texto;
  aviso.classList.toggle("error", esError);
  aviso.hidden = false;
}

/** Corre una acción contra el BFF, avisa el resultado y vuelve a leer lo que se ve. */
async function hacer(accion, textoDeExito) {
  try {
    await accion();
    avisar(t(textoDeExito));
    estado.etagPanel = null;
    await actualizarPanel();
    if (!$("vista-viaje").hidden && estado.viajeActual) await abrirViaje(estado.viajeActual);
    return true;
  } catch (error) {
    if (error instanceof ErrorDeApi && error.estadoHttp === 404 && estado.viajeActual) {
      mostrarVista("panel");  // el viaje ya no existe (eliminado o reagrupado)
    }
    avisar(t("accion.error", { motivo: error.message }), true);
    return false;
  }
}

const decidirReserva = (id, decision) => hacer(
  () => llamar("POST", `/reservas/${idDeRuta(id)}/confirmacion`, { cuerpo: { decision } }),
  decision === "confirmar" ? "porConfirmar.confirmada" : "porConfirmar.descartada");

function eliminarReserva(id) {
  if (!confirm(t("viaje.confirmarEliminarReserva"))) return;
  void hacer(() => llamar("DELETE", `/reservas/${idDeRuta(id)}`), "viaje.reservaEliminada");
}

function resolverConflicto(reservaId, conflictoId, valor) {
  // El valor de la carga manual es el que el viajero fijó: elegirlo es mantenerlo (ADR-0013).
  const cuerpo = valor.fuente === "manual"
    ? { eleccion: "mantenerFijado" } : { eleccion: "aceptarFuente", fuente: valor.fuente };
  void hacer(() => llamar("POST",
    `/reservas/${idDeRuta(reservaId)}/conflictos/${idDeRuta(conflictoId)}/resolucion`, { cuerpo }),
  "conflictos.resuelto");
}

async function archivarViaje() {
  const id = estado.viajeActual;
  if (await hacer(() => llamar("POST", `/viajes/${idDeRuta(id)}/archivo`), "viaje.archivado")) {
    await abrirViaje(id);
  }
}

async function eliminarViaje() {
  if (!confirm(t("viaje.confirmarEliminar"))) return;
  const id = estado.viajeActual;
  if (await hacer(() => llamar("DELETE", `/viajes/${idDeRuta(id)}`), "viaje.eliminado")) {
    estado.viajeActual = null;
    mostrarVista("panel");
  }
}

// --- vistas ----------------------------------------------------------------------------------

const VISTAS = ["panel", "viaje", "anteriores", "alta"];

function mostrarVista(nombre) {
  for (const vista of VISTAS) $(`vista-${vista}`).hidden = vista !== nombre;
  if (nombre !== "viaje") estado.viajeActual = null;
}

function valorLegible(valor) {
  if (valor && typeof valor === "object") return JSON.stringify(valor);
  if (typeof valor === "string" && /^\d{4}-\d{2}-\d{2}T/.test(valor)) return fechaLocal(valor, "UTC") + " UTC";
  return String(valor);
}

function dibujarConflicto(reserva, conflicto) {
  const caja = elemento("div", "conflicto");
  const campo = conflicto.campo.split(".").pop();
  caja.append(elemento("p", null, t("conflictos.campo", { campo: t("campos")[campo] || campo })));
  for (const valor of conflicto.valores) {
    const boton = elemento("button", "secundario", t("conflictos.elegir", {
      valor: valorLegible(valor.valor), fuente: t(`fuentes.${valor.fuente}`) }));
    boton.addEventListener("click", () => resolverConflicto(reserva.id, conflicto.id, valor));
    caja.append(boton);
  }
  return caja;
}

function dibujarReservaDelViaje(reserva) {
  const bloque = elemento("article", "reserva");
  const lista = elemento("ul", "tramos");
  for (const segmento of tramosOrdenados([reserva])) lista.append(dibujarTramo(segmento));
  bloque.append(lista);
  const codigos = reserva.identificadores.map((i) => i.codigo).join(", ");
  const datos = [t("viaje.fuentes", { fuentes: reserva.fuentes.map((f) => t(`fuentes.${f}`)).join(", ") })];
  if (codigos) datos.unshift(t("viaje.codigos", { codigos }));
  bloque.append(elemento("p", "sutil", datos.join(" · ")));
  const abiertos = (reserva.conflictosAbiertos || []).filter((c) => c.estado === "Abierto");
  if (abiertos.length) {
    bloque.append(elemento("h4", null, t("conflictos.titulo")));
    for (const conflicto of abiertos) bloque.append(dibujarConflicto(reserva, conflicto));
  }
  const eliminar = elemento("button", "peligro", t("viaje.eliminarReserva"));
  eliminar.addEventListener("click", () => eliminarReserva(reserva.id));
  bloque.append(eliminar);
  return bloque;
}

async function abrirViaje(id) {
  try {
    const { datos: viaje } = await llamar("GET", `/viajes/${idDeRuta(id)}`);
    mostrarVista("viaje");
    estado.viajeActual = viaje.id;
    $("titulo-viaje").textContent = viaje.titulo;
    const zona = viaje.reservas[0]?.segmentos[0]?.inicio.zonaHoraria || "UTC";
    $("resumen-viaje").textContent = `${t(`estadosDeViaje.${viaje.estado}`)} · ${t("panel.desdeHasta", {
      desde: fechaLocal(viaje.desde, zona, false), hasta: fechaLocal(viaje.hasta, zona, false) })} · ${
      t("panel.reservas", { cantidad: viaje.reservas.length })}`;
    $("archivar-viaje").hidden = viaje.estado !== "Completado";
    const reservas = $("reservas-del-viaje");
    reservas.replaceChildren(...viaje.reservas.map(dibujarReservaDelViaje));
  } catch (error) {
    avisar(t("accion.error", { motivo: error.message }), true);
  }
}

async function verAnteriores() {
  mostrarVista("anteriores");
  const lista = $("lista-anteriores");
  lista.replaceChildren();
  try {
    const paginas = await Promise.all(["Completado", "Archivado"].map(
      (estadoViaje) => llamar("GET", "/viajes", { consulta: { estado: estadoViaje, limite: 100 } })));
    const viajes = paginas.flatMap(({ datos }) => datos.viajes)
      .sort((a, b) => b.desde.localeCompare(a.desde));
    if (!viajes.length) lista.append(elemento("p", "sutil", t("anteriores.ninguno")));
    for (const viaje of viajes) {
      const fila = elemento("div", "viaje-encabezado");
      const enlace = elemento("button", "enlace", viaje.titulo);
      enlace.addEventListener("click", () => { void abrirViaje(viaje.id); });
      fila.append(enlace, elemento("span", "etiqueta", t(`estadosDeViaje.${viaje.estado}`)),
                  elemento("span", "sutil", t("panel.desdeHasta", {
                    desde: fechaLocal(viaje.desde, "UTC", false), hasta: fechaLocal(viaje.hasta, "UTC", false) })));
      lista.append(fila);
    }
  } catch (error) {
    avisar(t("accion.error", { motivo: error.message }), true);
  }
}

// --- carga manual (RF-06) --------------------------------------------------------------------

/** La hora `aaaa-mm-ddThh:mm` del lugar, en UTC (ADR-0032): se prueba el desplazamiento de la zona
    en ese momento con `Intl`, sin librerías. */
function aUtc(local, zona) {
  const supuesto = new Date(`${local}:00Z`);
  const partes = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: zona, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(supuesto)
    .map((p) => [p.type, p.value]));
  const enLaZona = Date.UTC(+partes.year, +partes.month - 1, +partes.day, +partes.hour,
                            +partes.minute, +partes.second);
  return new Date(supuesto.getTime() - (enLaZona - supuesto.getTime())).toISOString()
    .replace(".000Z", "Z");
}

function campoDeDetalle(nombre, esquema, requerido) {
  const id = `alta-detalle-${nombre}`;
  const etiqueta = elemento("label", null, t("campos")[nombre] || nombre);
  etiqueta.htmlFor = id;
  let control;
  if (esquema.enum) {
    control = elemento("select");
    if (!requerido) control.append(elemento("option", null, t("alta.sinElegir")));
    for (const valor of esquema.enum) {
      const opcion = elemento("option", null, t("valores")[valor] || valor);
      opcion.value = valor;
      control.append(opcion);
    }
  } else {
    control = elemento("input");
    if (esquema.type === "integer") Object.assign(control, { type: "number", min: esquema.minimum ?? 0 });
  }
  Object.assign(control, { id, required: requerido });
  control.dataset.campo = nombre;
  control.dataset.entero = String(esquema.type === "integer");
  return [etiqueta, control];
}

function dibujarDetalle() {
  const esquema = estado.esquemas[$("alta-tipo").value] || { properties: {} };
  const requeridos = new Set(esquema.required || []);
  const caja = $("alta-detalle");
  const leyenda = caja.querySelector("legend");
  caja.replaceChildren(leyenda);
  for (const [nombre, propiedad] of Object.entries(esquema.properties || {})) {
    caja.append(...campoDeDetalle(nombre, propiedad, requeridos.has(nombre)));
  }
}

function prepararAlta() {
  const tipos = $("alta-tipo");
  const iconos = t("iconos");
  tipos.replaceChildren(...Object.keys(estado.esquemas).sort().map((tipo) => {
    const opcion = elemento("option", null, `${iconos[presentacion({ tipo }).icono] || iconos.otro} ${tipo}`);
    opcion.value = tipo;
    return opcion;
  }));
  const zonas = $("zonas");
  zonas.replaceChildren(...(Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : [])
    .map((zona) => { const opcion = elemento("option"); opcion.value = zona; return opcion; }));
  const propia = Intl.DateTimeFormat().resolvedOptions().timeZone;
  for (const extremo of ["inicio", "fin"]) {
    if (!$(`alta-${extremo}-zona`).value) $(`alta-${extremo}-zona`).value = propia;
  }
  dibujarDetalle();
}

function extremo(nombre) {
  const zona = $(`alta-${nombre}-zona`).value.trim();
  return { instante: aUtc($(`alta-${nombre}-hora`).value, zona), precision: "instante",
           zonaHoraria: zona, lugar: { nombre: $(`alta-${nombre}-lugar`).value.trim(),
                                       pais: $(`alta-${nombre}-pais`).value.trim().toUpperCase(),
                                       zonaHoraria: zona } };
}

async function guardarAlta(evento) {
  evento.preventDefault();
  $("error-alta").hidden = true;
  const detalle = {};
  for (const control of $("alta-detalle").querySelectorAll("[data-campo]")) {
    const valor = control.value.trim();
    if (!valor || valor === t("alta.sinElegir")) continue;
    detalle[control.dataset.campo] = control.dataset.entero === "true" ? Number(valor) : valor;
  }
  let segmento;
  try {
    segmento = { tipo: $("alta-tipo").value, inicio: extremo("inicio"), fin: extremo("fin"),
                 operador: $("alta-operador").value.trim(), detalle };
  } catch {  // una zona horaria que Intl no conoce
    $("error-alta").textContent = t("alta.error", { motivo: t("alta.zona") });
    $("error-alta").hidden = false;
    return;
  }
  const referencia = $("alta-referencia").value.trim();
  if (referencia) segmento.referencia = referencia;
  try {
    await llamar("POST", "/reservas", { cuerpo: { segmentos: [segmento] }, clave: uuid() });
    $("form-alta").reset();
    prepararAlta();
    avisar(t("alta.guardada"));
    estado.etagPanel = null;
    mostrarVista("panel");
    await actualizarPanel();
  } catch (error) {
    $("error-alta").textContent = t("alta.error", { motivo: error.message });
    $("error-alta").hidden = false;
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
  $("ir-panel").addEventListener("click", () => { $("aviso").hidden = true; mostrarVista("panel"); });
  $("ir-anteriores").addEventListener("click", () => { $("aviso").hidden = true; void verAnteriores(); });
  $("ir-alta").addEventListener("click", () => { $("aviso").hidden = true; mostrarVista("alta"); });
  $("archivar-viaje").addEventListener("click", () => { void archivarViaje(); });
  $("eliminar-viaje").addEventListener("click", () => { void eliminarViaje(); });
  $("alta-tipo").addEventListener("change", dibujarDetalle);
  $("form-alta").addEventListener("submit", (evento) => { void guardarAlta(evento); });

  await cargarTipos().catch(() => { /* sin catálogo, los tramos se ven con la presentación genérica */ });
  prepararAlta();
  estado.token = guardado.leer("token");
  if (estado.token) await entrar(); else $("ingreso").hidden = false;
}

iniciar().catch(() => { $("ingreso").hidden = false; });
