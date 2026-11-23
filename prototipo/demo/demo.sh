#!/usr/bin/env bash
# Recorrido de demostración del prototipo, por bff-web, con las mismas operaciones que usa app-web.
#
# Uso, desde cualquier carpeta:
#   bash prototipo/demo/demo.sh            levanta lo que falte y deja los servicios arriba
#   bash prototipo/demo/demo.sh --bajar    al terminar baja solo los servicios (la base queda)
#
# Se detiene entre etapas (Enter para seguir). Cada corrida crea un viajero nuevo; con su correo se
# puede entrar a la página (http://localhost:18111) y ver lo mismo en el panel y el chat.
set -euo pipefail

PROTOTIPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROTOTIPO"
PY=".venv/bin/python"
BFF="http://localhost:18108"

titulo() { printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }
pausa()  { read -r -p $'\033[2m[Enter para seguir]\033[0m ' _; }
campo()  { "$PY" -c "import json,sys; d=json.load(sys.stdin); print(eval('d'+sys.argv[1]))" "$1"; }
nuevo_id() { "$PY" -c "import uuid; print(uuid.uuid4())"; }

titulo "1. Infraestructura y servicios"
make infra-arriba >/dev/null 2>&1
make servicios-arriba >/dev/null 2>&1
docker compose ps --format '  {{.Service}}: {{.Status}}'
pausa

titulo "2. Sesión OIDC (identity-access, simulado)"
CORREO="demo-$(date +%s)@ejemplo.com"
TOKEN=$(curl -s -X POST localhost:18103/sesiones -H 'Content-Type: application/json' \
  -d "{\"codigo\":\"oidc:$CORREO:AM\",\"verificadorPkce\":\"verificador-de-demostracion-0123456789-abcdefghij\",\"uriRedireccion\":\"http://localhost:18111/\"}" \
  | campo '["tokenAcceso"]')
SESION=(-H "Authorization: Bearer $TOKEN")
echo "  correo: $CORREO   (con este correo se entra a http://localhost:18111)"
pausa

titulo "3. Llegan las reservas"
echo "  La ida y la vuelta llegan por correo reenviado al alias del viajero"
echo "  (mail-ingest → booking-extraction → itinerary); el hotel se carga a mano por bff-web,"
echo "  y el boleto de tren llega por correo y lo lee su propio extractor (QA-15)."
"$PY" demo/cargar_viajes.py "$CORREO" | sed 's/^/  /'
pausa

titulo "4. El panel (GET /panel de bff-web)"
curl -s "$BFF/panel" "${SESION[@]}" | "$PY" -c '
import json,sys
p=json.load(sys.stdin)
for v in p["viajesActivos"]:
    print("  %s (%s): %s -> %s" % (v["titulo"], v["estado"], v["desde"], v["hasta"]))
    for r in v["reservas"]:
        s = r["segmentos"][0]
        print("    - %-6s %-9s %s  %s -> %s" % (s["tipo"], s.get("referencia", ""), s["inicio"]["instante"],
              s["inicio"]["lugar"]["nombre"], s["fin"]["lugar"]["nombre"]))
for r in p["porConfirmar"]:
    print("  por confirmar: %s %s" % (r["segmentos"][0]["tipo"], r["segmentos"][0].get("referencia", "")))'
pausa

titulo "5. El asistente (por bff-web)"
SID=$(curl -s -X POST "$BFF/asistente/sesiones" "${SESION[@]}" -H "Idempotency-Key: $(nuevo_id)" \
  -H 'Content-Type: application/vnd.trotamundos.v1+json' -d '{}' | campo '["id"]')
ULTIMA=""
decir() {
  echo -e "\n  \033[1mViajero:\033[0m ${2:-$1}"
  ULTIMA=$(curl -s -X POST "$BFF/asistente/sesiones/$SID/mensajes" "${SESION[@]}" \
    -H "Idempotency-Key: $(nuevo_id)" -H 'Content-Type: application/vnd.trotamundos.v1+json' -d "$1")
  echo "$ULTIMA" | "$PY" -c '
import json,sys
d=json.load(sys.stdin)
for m in d.get("mensajes",[]): print("  \033[1mAsistente:\033[0m", m)
if "accionPropuesta" in d: print("  \033[2m(propuesta", d["accionPropuesta"]["tipo"], ")\033[0m")
if "accionRealizada" in d: print("  \033[2m(realizada:", d["accionRealizada"]["tipo"], ")\033[0m")
if "detail" in d: print("  \033[31m", d.get("status"), d["detail"], "\033[0m")'
}
confirmar() {
  local accion
  accion=$(echo "$ULTIMA" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("accionPropuesta", {}).get("id", ""))')
  if [[ -z "$accion" ]]; then echo "  (no hay nada para confirmar)"; return; fi
  decir "{\"confirmacion\":{\"accionId\":\"$accion\",\"decision\":\"confirmar\"}}" "[botón: Confirmar]"
}
VIAJE=$(curl -s "$BFF/panel" "${SESION[@]}" | campo '["viajesActivos"][0]["id"]')
decir "{\"texto\":\"¿Cómo viene mi viaje?\",\"viajeId\":\"$VIAJE\"}" "¿Cómo viene mi viaje? (con el viaje elegido en la página)"
decir '{"texto":"¿A qué hora sale mi vuelo?"}' "¿A qué hora sale mi vuelo?"
decir '{"texto":"¿Cuándo sale mi tren?"}' "¿Cuándo sale mi tren?"
pausa

titulo "6. Problemas menores y corrección, siempre con confirmación (ADR-0038)"
decir '{"texto":"¿Tengo reservas por confirmar?"}' "¿Tengo reservas por confirmar?"
decir '{"texto":"confirmala"}' "confirmala"
confirmar
decir '{"texto":"me pasaron el vuelo AR1402 a las 22:30"}' "me pasaron el vuelo AR1402 a las 22:30"
confirmar
pausa

titulo "7. Disrupción del proveedor y derivación a la agencia (ADR-0039)"
echo "  La agencia preferida, por preferences; la cancelación, como la publicaría provider-sync:"
"$PY" demo/apoyo.py disrupcion "$CORREO" | sed 's/^/   - /'
sleep 2
decir '{"texto":"¿Se canceló mi vuelo?"}' "¿Se canceló mi vuelo?"
confirmar
CASO=$(echo "$ULTIMA" | campo '["accionRealizada"]["casoId"]')
echo -e "\n  \033[2mEl caso en support-liaison:\033[0m"
curl -s "localhost:18105/casos/$CASO" "${SESION[@]}" | "$PY" -m json.tool | sed 's/^/    /'
decir '{"texto":"¿Mi agencia ya recibió el caso?"}' "¿Mi agencia ya recibió el caso?"
pausa

echo -e "\n  Abrí http://localhost:18111 e ingresá con $CORREO para ver el panel y la conversación."
if [[ "${1:-}" == "--bajar" ]]; then
  titulo "Bajando solo los servicios (la base y el broker quedan)"
  mapfile -t servicios < <(docker compose config --services | grep -vxE 'postgres|postgres-eu|broker')
  docker compose rm -sf "${servicios[@]}"
fi
