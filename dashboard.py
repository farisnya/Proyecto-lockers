"""
dashboard.py — SmartLocker System
===================================
Dashboard Streamlit con conexión directa al servidor C++.

El usuario ingresa un código para ARRENDAR o DEVOLVER un locker.
La DLL (C++) envía el código al servidor y recibe la respuesta.

Ejecución:
  streamlit run dashboard.py

Cambiar IP del servidor en el sidebar si es otra PC.
"""

import streamlit as st
import ctypes
import os
import re
import random
import string
import threading
import time
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════
NUM_LOCKERS   = 10
REFRESH_SEG   = 2

# ═══════════════════════════════════════════════════════════════════
#  ESTADO COMPARTIDO  (persiste entre reruns de Streamlit)
# ═══════════════════════════════════════════════════════════════════
_lock = threading.Lock()

_estado = {
    "lockers": {
        str(i): {"ocupado": False, "codigo": "", "hora": ""}
        for i in range(1, NUM_LOCKERS + 1)
    },
    "total_ocupados":       0,
    "total_libres":         NUM_LOCKERS,
    "ultima_actualizacion": "Sin operaciones aún",
    "conectado":            False,
    "error":                "",
    "log":                  [],   # últimos 20 eventos
}

_lib_cache   = {"lib": None, "modo": None}
_conectado_f = {"valor": False}


# ═══════════════════════════════════════════════════════════════════
#  CARGA DE LIBRERÍA
# ═══════════════════════════════════════════════════════════════════

def _cargar_lib():
    if _lib_cache["lib"] is not None:
        return _lib_cache["lib"], _lib_cache["modo"]

    try:
        import lockers
        obj = lockers.SistemaLockers()
        _lib_cache["lib"]  = obj
        _lib_cache["modo"] = "swig"
        return obj, "swig"
    except ImportError:
        pass

    dll_path = Path(__file__).parent / "libreria_lockers.dll"
    if not dll_path.exists():
        return None, "no_dll"

    lib = ctypes.CDLL(str(dll_path))
    lib.conectar_c.argtypes        = [ctypes.c_char_p, ctypes.c_int]
    lib.conectar_c.restype         = ctypes.c_int
    lib.enviar_codigo_c.argtypes   = [ctypes.c_char_p]
    lib.enviar_codigo_c.restype    = ctypes.c_char_p
    lib.cantidad_ocupados_c.restype = ctypes.c_int
    lib.desconectar_c.argtypes     = []
    lib.desconectar_c.restype      = None

    _lib_cache["lib"]  = lib
    _lib_cache["modo"] = "ctypes"
    return lib, "ctypes"


# ═══════════════════════════════════════════════════════════════════
#  CONEXIÓN
# ═══════════════════════════════════════════════════════════════════

def conectar_servidor(ip: str, puerto: int) -> bool:
    lib, modo = _cargar_lib()
    if lib is None:
        with _lock:
            _estado["error"] = (
                "No se encontró libreria_lockers.dll ni el módulo SWIG.\n"
                "Ejecuta compilar.bat primero."
            )
        return False

    if _conectado_f["valor"]:
        return True

    if modo == "swig":
        ret = lib.conectar(ip, puerto)
    else:
        ret = lib.conectar_c(ip.encode(), puerto)

    if ret == 0:
        _conectado_f["valor"] = True
        with _lock:
            _estado["conectado"] = True
            _estado["error"]     = ""
        return True
    else:
        with _lock:
            _estado["error"] = (
                f"No se pudo conectar a {ip}:{puerto} (código {ret}).\n"
                "¿Está corriendo servidor.exe en esa PC?"
            )
        return False


# ═══════════════════════════════════════════════════════════════════
#  OPERACIÓN PRINCIPAL: enviar código
# ═══════════════════════════════════════════════════════════════════

def enviar_codigo(codigo: str) -> dict:
    """
    Envía el código al servidor C++ y actualiza el estado.
    Retorna un dict con los campos de la respuesta.
    """
    lib, modo = _cargar_lib()
    if lib is None or not _conectado_f["valor"]:
        return {"ok": False, "mensaje": "No conectado al servidor"}

    # Llamar a la DLL
    if modo == "swig":
        respuesta = lib.enviarCodigo(codigo)
    else:
        respuesta = lib.enviar_codigo_c(codigo.encode()).decode()

    # Parsear respuesta: "OCUPADO:Locker:N|Hora:...|Codigo:X"
    resultado = _parsear_respuesta(respuesta, codigo)
    _actualizar_estado(resultado)
    return resultado


def _parsear_respuesta(resp: str, codigo: str) -> dict:
    def extraer(clave):
        m = re.search(rf"{clave}([^|]+)", resp)
        return m.group(1).strip() if m else ""

    if "SIN_LOCKERS" in resp:
        return {
            "ok":      False,
            "accion":  "SIN_LOCKERS",
            "locker":  "",
            "hora":    extraer("Hora:"),
            "codigo":  codigo,
            "mensaje": "⚠️ No hay lockers disponibles",
            "raw":     resp,
        }

    accion = "OCUPADO" if "OCUPADO" in resp else "LIBERADO"
    locker = extraer("Locker:")
    hora   = extraer("Hora:")

    if accion == "OCUPADO":
        msg = f"✅ Locker **#{locker}** asignado — código `{codigo}`"
    else:
        msg = f"🔓 Locker **#{locker}** liberado — código `{codigo}` devuelto"

    return {
        "ok":      True,
        "accion":  accion,
        "locker":  locker,
        "hora":    hora,
        "codigo":  codigo,
        "mensaje": msg,
        "raw":     resp,
    }


def _actualizar_estado(r: dict):
    if not r["ok"] or not r["locker"]:
        return
    locker = r["locker"]
    with _lock:
        if r["accion"] == "OCUPADO":
            _estado["lockers"][locker] = {
                "ocupado": True,
                "codigo":  r["codigo"],
                "hora":    r["hora"],
            }
        else:
            _estado["lockers"][locker] = {
                "ocupado": False,
                "codigo":  "",
                "hora":    r["hora"],
            }

        ocupados = sum(1 for v in _estado["lockers"].values() if v["ocupado"])
        _estado["total_ocupados"]       = ocupados
        _estado["total_libres"]         = NUM_LOCKERS - ocupados
        _estado["ultima_actualizacion"] = datetime.now().strftime("%H:%M:%S")

        _estado["log"].append({
            "hora":    datetime.now().strftime("%H:%M:%S"),
            "accion":  r["accion"],
            "locker":  r["locker"],
            "codigo":  r["codigo"],
        })
        if len(_estado["log"]) > 20:
            _estado["log"].pop(0)


# ═══════════════════════════════════════════════════════════════════
#  HELPERS UI
# ═══════════════════════════════════════════════════════════════════

def codigo_aleatorio():
    letras  = random.choices(string.ascii_uppercase, k=3)
    digitos = random.choices(string.digits, k=3)
    return "".join(letras + digitos)


def render_card(num: int, info: dict) -> str:
    ocupado  = info["ocupado"]
    codigo   = info["codigo"] or "—"
    hora     = info["hora"][-8:] if info["hora"] else ""
    css      = "locker-ocupado" if ocupado else "locker-libre"
    icono    = "🔴" if ocupado else "🟢"
    color    = "#e74c3c" if ocupado else "#2ecc71"
    estado   = "OCUPADO" if ocupado else "LIBRE"
    cod_h    = f'<div class="lk-cod">{codigo}</div>'   if ocupado else ""
    hora_h   = f'<div class="lk-hora">{hora}</div>'   if hora    else ""
    return f"""
    <div class="{css}">
      <div class="lk-num" style="color:{color};">{icono} {num:02d}</div>
      <div class="lk-est" style="color:{color};">{estado}</div>
      {cod_h}{hora_h}
    </div>"""


CSS = """
<style>
.locker-libre,.locker-ocupado{border-radius:12px;padding:16px 10px;
  text-align:center;margin:4px;}
.locker-libre  {background:linear-gradient(135deg,#1a2a1a,#1e3a1e);
  border:2px solid #2ecc71;box-shadow:0 0 10px rgba(46,204,113,.2);}
.locker-ocupado{background:linear-gradient(135deg,#2a1a1a,#3a1e1e);
  border:2px solid #e74c3c;box-shadow:0 0 12px rgba(231,76,60,.3);}
.lk-num{font-size:2rem;font-weight:700;margin-bottom:3px;}
.lk-est{font-size:0.78rem;font-weight:600;letter-spacing:1px;text-transform:uppercase;}
.lk-cod{font-size:0.88rem;font-family:monospace;margin-top:5px;opacity:.9;}
.lk-hora{font-size:0.66rem;margin-top:3px;opacity:.6;}
.dot-on {display:inline-block;width:9px;height:9px;border-radius:50%;
  background:#2ecc71;box-shadow:0 0 5px #2ecc71;margin-right:5px;}
.dot-off{display:inline-block;width:9px;height:9px;border-radius:50%;
  background:#e74c3c;box-shadow:0 0 5px #e74c3c;margin-right:5px;}
</style>"""


# ═══════════════════════════════════════════════════════════════════
#  UI PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="SmartLocker System",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    st.title("📦 SmartLocker")
    st.caption("Sistema inteligente de lockers")
    st.divider()

    st.subheader("🔌 Conexión al servidor")
    ip_srv   = st.text_input("IP del servidor",  value="127.0.0.1",
                              help="Cambia a la IP de la otra PC si es red LAN")
    port_srv = st.number_input("Puerto", value=8888, step=1)

    conectado = _estado["conectado"]
    error_msg = _estado["error"]

    if conectado:
        st.markdown('<span class="dot-on"></span>**Conectado**',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="dot-off"></span>**Desconectado**',
                    unsafe_allow_html=True)
        if st.button("🔗 Conectar"):
            conectar_servidor(ip_srv, int(port_srv))
            st.rerun()
        if error_msg:
            st.error(error_msg)

    st.divider()
    st.subheader("⚙️ Vista")
    refresh_rate = st.slider("Actualización (seg)", 1, 10, REFRESH_SEG)
    solo_ocupados = st.checkbox("Solo ocupados", value=False)

# ── Header ────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='background:linear-gradient(90deg,#3498db,#2ecc71);"
    "-webkit-background-clip:text;-webkit-text-fill-color:transparent;"
    "font-size:2.2rem;font-weight:800;'>📦 SmartLocker System</h1>",
    unsafe_allow_html=True,
)
st.caption("Monitoreo en tiempo real · Arriendo y devolución de lockers")
st.markdown("---")

# ── Panel de arriendo / devolución ────────────────────────────────
st.subheader("🔑 Arrendar / Devolver locker")

col_inp, col_btn, col_sim = st.columns([3, 1, 1])

with col_inp:
    codigo_inp = st.text_input(
        "Código de paquete",
        placeholder="Ej: ABC123",
        max_chars=6,
        label_visibility="collapsed",
    )

with col_btn:
    enviar = st.button("📨 Enviar", use_container_width=True,
                       disabled=not _estado["conectado"])

with col_sim:
    simular = st.button("🎲 Aleatorio", use_container_width=True,
                        disabled=not _estado["conectado"],
                        help="Genera y envía un código aleatorio")

# Manejar acciones
resultado_mostrar = None

if enviar and codigo_inp.strip():
    codigo_limpio = codigo_inp.strip().upper()
    resultado_mostrar = enviar_codigo(codigo_limpio)

if simular:
    cod_rand = codigo_aleatorio()
    # Si ya hay algún código en uso, simular también devolución aleatoria
    with _lock:
        ocupados_actuales = [
            v["codigo"] for v in _estado["lockers"].values()
            if v["ocupado"]
        ]
    if ocupados_actuales and random.random() < 0.4:
        cod_rand = random.choice(ocupados_actuales)
    resultado_mostrar = enviar_codigo(cod_rand)

if resultado_mostrar:
    if resultado_mostrar.get("ok"):
        st.success(resultado_mostrar["mensaje"])
    else:
        st.warning(resultado_mostrar["mensaje"])

st.markdown("---")

# ── Métricas ──────────────────────────────────────────────────────
with _lock:
    lockers_data   = dict(_estado["lockers"])
    total_ocupados = _estado["total_ocupados"]
    total_libres   = _estado["total_libres"]
    ultima_act     = _estado["ultima_actualizacion"]
    log_eventos    = list(_estado["log"])

c1, c2, c3, c4 = st.columns(4)
c1.metric("📦 Total",         NUM_LOCKERS)
c2.metric("🔴 Ocupados",      total_ocupados)
c3.metric("🟢 Disponibles",   total_libres)
c4.metric("📊 Ocupación",     f"{(total_ocupados/NUM_LOCKERS*100):.0f}%")

# Barra de ocupación
pct   = total_ocupados / NUM_LOCKERS * 100
color = "#e74c3c" if pct > 70 else "#f39c12" if pct > 40 else "#2ecc71"
st.markdown(f"""
<div style="background:#1e1e2e;border-radius:10px;padding:12px 20px;margin:12px 0;">
  <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
    <span style="color:#aaa;font-size:.85rem;">Ocupación global</span>
    <span style="color:{color};font-weight:700;">{pct:.0f}%</span>
  </div>
  <div style="background:#333;border-radius:6px;height:10px;">
    <div style="background:{color};width:{pct:.1f}%;height:10px;border-radius:6px;"></div>
  </div>
</div>""", unsafe_allow_html=True)

st.caption(f"🕐 Última operación: {ultima_act}")

# ── Grid de lockers ───────────────────────────────────────────────
st.subheader("🗄️ Estado de Lockers")

lockers_f = [
    (int(k), v)
    for k, v in sorted(lockers_data.items(), key=lambda x: int(x[0]))
    if not solo_ocupados or v["ocupado"]
]

if not lockers_f:
    st.info("Ningún locker ocupado.")
else:
    POR_FILA = 5
    for i in range(0, len(lockers_f), POR_FILA):
        cols = st.columns(POR_FILA)
        for j, (num, info) in enumerate(lockers_f[i:i + POR_FILA]):
            with cols[j]:
                st.markdown(render_card(num, info), unsafe_allow_html=True)

# ── Log de operaciones ────────────────────────────────────────────
st.markdown("---")
st.subheader("📋 Historial de operaciones")

if log_eventos:
    filas = [
        {
            "Hora":    e["hora"],
            "Acción":  "✅ ARRENDADO" if e["accion"] == "OCUPADO" else "🔓 DEVUELTO",
            "Locker":  f"#{e['locker']}",
            "Código":  e["codigo"],
        }
        for e in reversed(log_eventos)
    ]
    st.table(filas)
else:
    st.info("Sin operaciones aún. Ingresa un código arriba para comenzar.")

# ── Auto-refresh ──────────────────────────────────────────────────
time.sleep(refresh_rate)
st.rerun()
