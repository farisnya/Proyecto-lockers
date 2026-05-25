
import ctypes
import os
import sys
import time
import platform
import random
import string
from datetime import datetime
from threading import Thread

import streamlit as st

# ── Configuración página ────────────────────────────────────
st.set_page_config(
    page_title="Sistema de Lockers",
    page_icon="🔐",
    layout="wide"
)

# ── Estilos ─────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');

.stApp { background-color: #080d16; font-family: 'DM Sans', sans-serif; }
h1,h2,h3,h4,p,label,div { font-family: 'DM Sans', sans-serif; }

.dash-header {
    display:flex; align-items:center; gap:16px;
    padding:24px 0 8px; border-bottom:1px solid rgba(255,255,255,0.07);
    margin-bottom:24px;
}
.dash-title   { font-size:24px; font-weight:600; color:#f0f4ff; margin:0; letter-spacing:-0.5px; }
.dash-sub     { font-size:12px; color:#4a5a72; margin:0; }

.metric-row   { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:24px; }
.metric-card  { background:#0f1826; border:1px solid rgba(255,255,255,0.07); border-radius:14px; padding:18px 20px; }
.metric-val   { font-size:34px; font-weight:700; line-height:1; font-family:'Space Mono',monospace; }
.metric-lbl   { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.07em; color:#3a4a62 !important; margin-top:4px; }
.mv-red       { color:#f87171; }
.mv-green     { color:#34d399; }
.mv-blue      { color:#60a5fa; }
.mv-amber     { color:#fbbf24; }

.locker-grid  { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:24px; }
.locker-cell  { border-radius:14px; padding:16px; display:flex; flex-direction:column;
                 align-items:center; gap:6px; min-height:105px; justify-content:center;
                 transition:transform .15s,box-shadow .15s; }
.locker-libre  { background:linear-gradient(135deg,#0a1f14,#0d2b1a); border:1.5px solid #1a4731; }
.locker-ocupado{ background:linear-gradient(135deg,#1a0808,#250d0d); border:1.5px solid #5a1a1a; }
.locker-num   { font-family:'Space Mono',monospace; font-size:20px; font-weight:700; line-height:1; }
.locker-num-libre   { color:#34d399; }
.locker-num-ocupado { color:#f87171; }
.locker-tag   { font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.1em; }
.locker-tag-libre   { color:#1a6644; }
.locker-tag-ocupado { color:#7f2020; }
.locker-codigo{ font-size:10px; color:#94a3b8; font-family:'Space Mono',monospace; text-align:center; word-break:break-all; }
.locker-icon  { font-size:20px; }

.event-row    { display:flex; align-items:center; gap:12px; padding:11px 14px;
                border-radius:10px; border:1px solid rgba(255,255,255,0.05);
                margin-bottom:7px; background:#0c1523; }
.event-dot-ocu{ width:8px; height:8px; border-radius:50%; background:#f87171; flex-shrink:0; }
.event-dot-lib{ width:8px; height:8px; border-radius:50%; background:#34d399; flex-shrink:0; }
.event-estado { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; min-width:68px; }
.ev-ocu { color:#f87171; }
.ev-lib { color:#34d399; }
.event-info   { font-size:13px; color:#cbd5e1; flex:1; }
.event-hora   { font-family:'Space Mono',monospace; font-size:11px; color:#4a5a72; }
.event-origen { font-size:10px; padding:2px 7px; border-radius:8px; font-weight:600;
                text-transform:uppercase; letter-spacing:0.05em; }
.ev-local  { background:#0f2b1a; color:#34d399; border:1px solid #1a4731; }
.ev-remoto { background:#1a1f0f; color:#fbbf24; border:1px solid #3a400f; }
.ev-server { background:#0f1a2b; color:#60a5fa; border:1px solid #1a2b4a; }

.sec-title    { font-size:12px; font-weight:600; text-transform:uppercase;
                letter-spacing:0.1em; color:#3a4a62 !important; margin-bottom:12px; }

.badge-on  { background:#052e16; color:#4ade80; padding:4px 12px; border-radius:20px;
             font-size:12px; font-weight:600; display:inline-block; border:1px solid #166534; }
.badge-off { background:#1c0606; color:#f87171; padding:4px 12px; border-radius:20px;
             font-size:12px; font-weight:600; display:inline-block; border:1px solid #7f1d1d; }
.badge-wait{ background:#1c1206; color:#fbbf24; padding:4px 12px; border-radius:20px;
             font-size:12px; font-weight:600; display:inline-block; border:1px solid #92400e; }

/* Aviso locker ocupado */
.aviso-ocupado {
    background: linear-gradient(90deg,#1a0808,#0c1523);
    border: 1px solid #f87171; border-radius:10px;
    padding:10px 16px; margin-bottom:12px;
    font-size:13px; color:#f87171;
}
/* Notificación de evento remoto */
.notif-remoto {
    background: linear-gradient(90deg,#1a1f0f,#0c1523);
    border: 1px solid #fbbf24; border-radius:10px;
    padding:10px 16px; margin-bottom:12px;
    font-size:13px; color:#fbbf24;
}

[data-testid="stSidebar"]   { background-color:#080d16 !important; border-right:1px solid rgba(255,255,255,0.06); }
[data-testid="stSidebar"] * { color:#c0cfe0 !important; }
[data-testid="stSidebar"] .stButton > button {
    background:#0f1826; border:1px solid rgba(255,255,255,0.1);
    color:#c0cfe0 !important; border-radius:10px; font-size:13px;
    font-weight:500; width:100%; padding:9px;
}
.stButton > button {
    background:#0f1826; border:1px solid rgba(255,255,255,0.1);
    color:#c0cfe0 !important; border-radius:10px; font-size:13px;
    font-weight:500; width:100%; padding:9px;
}
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
    background-color:#0f1826 !important; color:#c0cfe0 !important;
    border:1px solid rgba(255,255,255,0.1) !important; border-radius:8px !important;
}
#MainMenu, footer, header { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

# ── Cargar DLL ──────────────────────────────────────────────
TOTAL_LOCKERS = 10
_so_ext  = "dll" if platform.system() == "Windows" else "so"
_dll_name = f"libreria_lockers.{_so_ext}"
_dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _dll_name)

@st.cache_resource
def cargar_dll(ruta):
    if not os.path.exists(ruta):
        return None, f"No se encontró {ruta}\nCompila primero con compilar.bat"
    try:
        lib = ctypes.CDLL(ruta)

        # ── Prototipos originales ───────────────────────────
        lib.conectar.argtypes          = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.conectar.restype           = ctypes.c_int
        lib.desconectar.argtypes       = []
        lib.desconectar.restype        = None
        lib.esta_conectado.argtypes    = []
        lib.esta_conectado.restype     = ctypes.c_int
        lib.esta_corriendo.argtypes    = []
        lib.esta_corriendo.restype     = ctypes.c_int
        lib.hay_mensaje.argtypes       = []
        lib.hay_mensaje.restype        = ctypes.c_int
        lib.mensajes_pendientes.argtypes = []
        lib.mensajes_pendientes.restype  = ctypes.c_int
        lib.leer_mensaje_crudo.argtypes  = []
        lib.leer_mensaje_crudo.restype   = ctypes.c_char_p
        lib.procesar_dato.argtypes     = [ctypes.c_char_p]
        lib.procesar_dato.restype      = ctypes.c_char_p
        lib.cantidad_ocupados.argtypes = []
        lib.cantidad_ocupados.restype  = ctypes.c_int
        lib.ultimo_error.argtypes      = []
        lib.ultimo_error.restype       = ctypes.c_char_p

        # ── Funciones multi-PC ──────────────────────────────
        lib.enviar_ocupar.argtypes  = [ctypes.c_int, ctypes.c_char_p]
        lib.enviar_ocupar.restype   = ctypes.c_int
        lib.enviar_liberar.argtypes = [ctypes.c_int, ctypes.c_char_p]
        lib.enviar_liberar.restype  = ctypes.c_int

        return lib, ""
    except Exception as e:
        return None, str(e)

lib, dll_error = cargar_dll(_dll_path)

# ── Session state ───────────────────────────────────────────
def init_state():
    defaults = {
        "historial":          [],
        "lockers_ocupados":   {},    # locker_str -> codigo
        "ip":                 "127.0.0.1",
        "puerto":             8888,
        "reconectar":         True,
        "ultima_notif":       "",
        "aviso_ocupado":      "",    # mensaje cuando locker ya está ocupado
        # ── Comandos enviados localmente, esperando confirmación del servidor.
        # Cada elemento es una tupla (locker_str, codigo, accion).
        # Cuando llega el broadcast de vuelta, si coincide → origen=LOCAL.
        "pending_local":      set(),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ── Helpers ─────────────────────────────────────────────────
def dll_conectada():
    return lib is not None and lib.esta_conectado() == 1

def dll_corriendo():
    return lib is not None and lib.esta_corriendo() == 1

def registrar_evento(estado, codigo, locker, hora, origen="LOCAL"):
    ev = {"hora": hora, "codigo": codigo, "locker": str(locker),
          "estado": estado, "origen": origen}
    st.session_state.historial.insert(0, ev)
    st.session_state.historial = st.session_state.historial[:100]
    lok = str(locker)
    if estado == "OCUPADO":
        st.session_state.lockers_ocupados[lok] = codigo
    else:
        st.session_state.lockers_ocupados.pop(lok, None)

def ocupar_locker(num: int, codigo: str):
    """
    Intenta ocupar el locker `num` con el código dado.
    - Si el locker ya está ocupado localmente: muestra aviso sin enviar nada.
    - Si hay conexión: envía CMD:OCUPAR al servidor y marca la operación
      como pendiente local (para reconocer el propio broadcast de vuelta).
    - Si no hay conexión: registra en modo local.
    """
    lok = str(num)
    codigo = codigo.strip().upper()
    if not codigo:
        st.session_state.aviso_ocupado = "⚠️ Debes ingresar un código."
        return

    # Verificar si ya está ocupado localmente
    if lok in st.session_state.lockers_ocupados:
        cod_actual = st.session_state.lockers_ocupados[lok]
        st.session_state.aviso_ocupado = (
            f"🔒 El Locker #{num} ya está ocupado con el código: {cod_actual}. "
            "Debes liberarlo antes de arrendar."
        )
        return

    st.session_state.aviso_ocupado = ""
    hora = datetime.now().strftime("%H:%M:%S")

    if dll_conectada():
        # Marcar como pendiente para reconocer el broadcast de vuelta como LOCAL
        pl = set(st.session_state.pending_local)
        pl.add((lok, codigo, "OCUPADO"))
        st.session_state.pending_local = pl
        lib.enviar_ocupar(num, codigo.encode())
    else:
        # Modo local sin servidor
        registrar_evento("OCUPADO", codigo, lok, hora, "LOCAL")

def liberar_locker(num: int):
    """
    Libera el locker `num`.
    - Si el locker ya está libre: muestra aviso.
    - Si hay conexión: envía CMD:LIBERAR al servidor y marca como pendiente local.
    - Si no hay conexión: libera en modo local.
    """
    lok = str(num)
    cod = st.session_state.lockers_ocupados.get(lok)
    if not cod:
        st.session_state.aviso_ocupado = f"ℹ️ El Locker #{num} ya está libre."
        return

    st.session_state.aviso_ocupado = ""
    hora = datetime.now().strftime("%H:%M:%S")

    if dll_conectada():
        pl = set(st.session_state.pending_local)
        pl.add((lok, cod, "LIBERADO"))
        st.session_state.pending_local = pl
        lib.enviar_liberar(num, cod.encode())
    else:
        registrar_evento("LIBERADO", cod, lok, hora, "LOCAL")

# ── Procesar cola DLL ───────────────────────────────────────
def procesar_dll():
    """
    Lee todos los mensajes crudos de la cola de la DLL y actualiza el estado.

    CAMBIO CLAVE vs versión anterior:
    - Ya NO usa procesar_dato() (la DLL usaba lógica de toggle código→locker,
      incompatible con el protocolo nuevo |IP:|Accion: del servidor).
    - Parsea el mensaje crudo directamente en Python leyendo |Accion: explícito.
    - Detecta el origen (LOCAL / REMOTO / SERVIDOR) con un conjunto
      de operaciones pendientes (pending_local) en vez de heurísticas frágiles.

    Protocolo broadcast actual del servidor:
        Codigo:ABC123|Hora:HH:MM:SS|Locker:N|IP:x.x.x.x|Accion:OCUPADO/LIBERADO
    Snapshot al conectar:
        Codigo:XYZ|Hora:...|Locker:N|IP:SERVIDOR|Accion:OCUPADO
    Errores:
        ERROR:LOCKER_OCUPADO|Locker:N|CodigoActual:X
        ERROR:LOCKER_LIBRE|Locker:N
        ERROR:CODIGO_INCORRECTO|Locker:N
    """
    if lib is None:
        return

    while lib.hay_mensaje():
        crudo = lib.leer_mensaje_crudo()
        if not crudo:
            break
        crudo_str = crudo.decode(errors="ignore").strip()
        if not crudo_str:
            continue

        # ── Mensajes de error del servidor ──────────────────
        if crudo_str.startswith("ERROR:"):
            if "LOCKER_OCUPADO" in crudo_str:
                lok_err, cod_err = "", ""
                try:
                    lok_err = crudo_str.split("Locker:")[1].split("|")[0].strip()
                except Exception:
                    pass
                try:
                    cod_err = crudo_str.split("CodigoActual:")[1].split("|")[0].strip()
                except Exception:
                    pass
                st.session_state.aviso_ocupado = (
                    f"🔒 El servidor indica que el Locker #{lok_err} ya está ocupado"
                    + (f" con el código: {cod_err}." if cod_err else ".")
                )
            elif "LOCKER_LIBRE" in crudo_str:
                lok_err = ""
                try:
                    lok_err = crudo_str.split("Locker:")[1].split("|")[0].strip()
                except Exception:
                    pass
                st.session_state.aviso_ocupado = (
                    f"ℹ️ El servidor indica que el Locker #{lok_err} ya estaba libre."
                )
            elif "CODIGO_INCORRECTO" in crudo_str:
                lok_err = ""
                try:
                    lok_err = crudo_str.split("Locker:")[1].split("|")[0].strip()
                except Exception:
                    pass
                st.session_state.aviso_ocupado = (
                    f"⚠️ Código incorrecto para el Locker #{lok_err}."
                )
            continue

        # ── Parsear broadcast / snapshot ─────────────────────
        # Formato: Codigo:X|Hora:HH:MM:SS|Locker:N|IP:Z|Accion:OCUPADO
        if "Codigo:" not in crudo_str:
            continue

        fields: dict[str, str] = {}
        for part in crudo_str.split("|"):
            if ":" in part:
                k, _, v = part.partition(":")
                fields[k.strip()] = v.strip()

        codigo = fields.get("Codigo", "")
        hora   = fields.get("Hora", "")[:8]
        locker = fields.get("Locker", "")
        accion = fields.get("Accion", "")   # OCUPADO o LIBERADO (campo explícito)
        ip     = fields.get("IP", "")

        if not codigo or not locker:
            continue

        # Si el servidor no envió |Accion: (protocolo viejo) no procesamos.
        if accion not in ("OCUPADO", "LIBERADO"):
            continue

        # ── Determinar origen ────────────────────────────────
        # pending_local = operaciones que este PC envió al servidor y aún
        # no recibió de vuelta como broadcast.
        key    = (locker, codigo, accion)
        pl     = set(st.session_state.pending_local)
        if key in pl:
            origen = "LOCAL"
            pl.discard(key)
            st.session_state.pending_local = pl
        elif ip == "SERVIDOR":
            origen = "SERVIDOR"   # snapshot inicial al conectar
        else:
            origen = "REMOTO"     # otro PC

        # ── Actualizar estado ────────────────────────────────
        # Usamos locker + accion directamente (no toggle).
        registrar_evento(accion, codigo, locker, hora, origen)

        # Limpiar aviso de error previo si la operación fue exitosa
        st.session_state.aviso_ocupado = ""

        if origen == "REMOTO":
            ico = "🔒" if accion == "OCUPADO" else "🔓"
            st.session_state.ultima_notif = (
                f"{ico} Evento remoto: Locker #{locker} {accion} [{codigo}] — {hora}"
            )

# ── SIDEBAR ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔐 Lockers")
    st.markdown("---")

    if dll_error:
        st.error(f"DLL no cargada:\n{dll_error}")
    else:
        st.markdown('<span class="badge-on">● DLL cargada</span>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**Servidor C++**")
    ip_in    = st.text_input("IP del servidor", value=st.session_state.ip)
    port_in  = st.number_input("Puerto", value=st.session_state.puerto,
                                min_value=1, max_value=65535)
    recon_in = st.checkbox("Reconexión automática", value=st.session_state.reconectar)
    st.markdown("---")

    if lib is not None:
        if not dll_corriendo():
            if st.button("🔌 Conectar al servidor"):
                st.session_state.ip         = ip_in
                st.session_state.puerto     = int(port_in)
                st.session_state.reconectar = recon_in
                st.session_state.historial  = []
                st.session_state.lockers_ocupados = {}
                st.session_state.ultima_notif     = ""
                st.session_state.aviso_ocupado    = ""
                lib.conectar(ip_in.encode(), int(port_in), 1 if recon_in else 0)
        elif dll_corriendo() and not dll_conectada():
            st.markdown('<span class="badge-wait">⏳ Conectando…</span>', unsafe_allow_html=True)
            if st.button("✖ Cancelar"):
                lib.desconectar()
        else:
            if st.button("⛔ Desconectar"):
                lib.desconectar()

    st.markdown("---")
    if dll_conectada():
        err = lib.ultimo_error().decode(errors="ignore")
        st.markdown('<span class="badge-on">● CONECTADO</span>', unsafe_allow_html=True)
        st.caption(f"📡 {err}")
    elif dll_corriendo():
        err = lib.ultimo_error().decode(errors="ignore")
        st.markdown('<span class="badge-wait">⏳ RECONECTANDO</span>', unsafe_allow_html=True)
        st.caption(err)
    else:
        st.markdown('<span class="badge-off">● DESCONECTADO</span>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**Arrendar locker**")
    with st.expander("🔒 Ocupar locker"):
        n_ocu = st.number_input("Nº locker", 1, TOTAL_LOCKERS, key="n_ocu")
        c_ocu = st.text_input("Código / placa", key="c_ocu", placeholder="Ej: ABC123")
        if st.button("Arrendar", key="btn_ocu"):
            ocupar_locker(n_ocu, c_ocu)
            st.rerun()

    with st.expander("🔓 Liberar locker"):
        n_lib = st.number_input("Nº locker", 1, TOTAL_LOCKERS, key="n_lib")
        if st.button("Devolver", key="btn_lib"):
            liberar_locker(n_lib)
            st.rerun()

    st.markdown("---")
    if st.button("🗑 Limpiar historial"):
        st.session_state.historial = []
        st.session_state.lockers_ocupados = {}
        st.session_state.ultima_notif     = ""
        st.session_state.aviso_ocupado    = ""

    st.markdown("---")
    st.caption(f"IP: `{st.session_state.ip}:{st.session_state.puerto}`")
    st.caption(f"DLL: `{_dll_name}`")

    # ── Leyenda ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**Leyenda de eventos**")
    st.markdown(
        '<span class="event-origen ev-local">LOCAL</span> Este PC<br>'
        '<span class="event-origen ev-remoto">REMOTO</span> Otro PC cliente<br>'
        '<span class="event-origen ev-server">SERVIDOR</span> Confirmación del servidor',
        unsafe_allow_html=True
    )

# ── Leer mensajes de la DLL (solo actualizar estado) ────────
procesar_dll()

# ── HEADER ──────────────────────────────────────────────────
st.markdown("""
<div class="dash-header">
  <div style="font-size:32px">🔐</div>
  <div>
    <p class="dash-title">Sistema Inteligente de Lockers</p>
    <p class="dash-sub">Dashboard multi-PC — arriendo y devolución manual · servidor C++ · librería dinámica</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── AVISOS ───────────────────────────────────────────────────
if st.session_state.aviso_ocupado:
    st.markdown(
        f'<div class="aviso-ocupado">{st.session_state.aviso_ocupado}</div>',
        unsafe_allow_html=True
    )

if st.session_state.ultima_notif:
    st.markdown(
        f'<div class="notif-remoto">⚡ {st.session_state.ultima_notif}</div>',
        unsafe_allow_html=True
    )

# ── MÉTRICAS ────────────────────────────────────────────────
ocupados_cnt = len(st.session_state.lockers_ocupados)
libres_cnt   = TOTAL_LOCKERS - ocupados_cnt
eventos_cnt  = len(st.session_state.historial)
hora_ahora   = datetime.now().strftime("%H:%M:%S")

st.markdown(f"""
<div class="metric-row">
  <div class="metric-card"><div class="metric-val mv-red">{ocupados_cnt}</div><div class="metric-lbl">Lockers ocupados</div></div>
  <div class="metric-card"><div class="metric-val mv-green">{libres_cnt}</div><div class="metric-lbl">Lockers libres</div></div>
  <div class="metric-card"><div class="metric-val mv-blue">{eventos_cnt}</div><div class="metric-lbl">Eventos</div></div>
  <div class="metric-card"><div class="metric-val mv-amber" style="font-size:24px">{hora_ahora}</div><div class="metric-lbl">Hora actual</div></div>
</div>
""", unsafe_allow_html=True)

# ── GRID DE LOCKERS ─────────────────────────────────────────
st.markdown(
    '<p class="sec-title">Estado de lockers — usa los botones debajo de cada locker para arrendar o devolver</p>',
    unsafe_allow_html=True
)

mapa = {str(lok): cod for lok, cod in st.session_state.lockers_ocupados.items()}

celdas = ""
for i in range(1, TOTAL_LOCKERS + 1):
    n = str(i)
    if n in mapa:
        cod   = mapa[n]
        short = cod[:7] + "…" if len(cod) > 7 else cod
        celdas += f"""
        <div class="locker-cell locker-ocupado">
            <div class="locker-icon">🔒</div>
            <div class="locker-num locker-num-ocupado">{i:02d}</div>
            <div class="locker-tag locker-tag-ocupado">Ocupado</div>
            <div class="locker-codigo">{short}</div>
        </div>"""
    else:
        celdas += f"""
        <div class="locker-cell locker-libre">
            <div class="locker-icon">🔓</div>
            <div class="locker-num locker-num-libre">{i:02d}</div>
            <div class="locker-tag locker-tag-libre">Libre</div>
        </div>"""

st.markdown(f'<div class="locker-grid">{celdas}</div>', unsafe_allow_html=True)

# ── Botones por locker ───────────────────────────────────────
# Arrendar locker libre / devolver locker ocupado
cols = st.columns(TOTAL_LOCKERS)
for i, col in enumerate(cols):
    num = i + 1
    lok = str(num)
    with col:
        if lok in mapa:
            # Locker ocupado → botón para liberar
            if st.button(f"🔓{num}", key=f"lb{num}", help=f"Devolver locker {num}"):
                liberar_locker(num)
                st.rerun()
        else:
            # Locker libre → botón para ocupar (pide código en sidebar)
            if st.button(f"🔒{num}", key=f"oc{num}",
                         help=f"Arrendar locker {num} — ingresa el código en el panel lateral"):
                # Intentar con el código que haya en el campo del sidebar
                cod_sidebar = st.session_state.get("c_ocu", "").strip().upper()
                if cod_sidebar:
                    ocupar_locker(num, cod_sidebar)
                else:
                    st.session_state.aviso_ocupado = (
                        f"⚠️ Para arrendar el Locker #{num}, "
                        "escribe un código en el campo del panel lateral y luego presiona el botón."
                    )
                st.rerun()

st.markdown("---")

# ── ACTIVIDAD + OCUPACIÓN ────────────────────────────────────
lcol, rcol = st.columns([3, 2])

with lcol:
    st.markdown('<p class="sec-title">📡 Actividad reciente</p>', unsafe_allow_html=True)
    if not st.session_state.historial:
        msg = "Conectado. Esperando eventos…" if dll_conectada() \
              else "Configura la IP y presiona Conectar, o usa el panel lateral para operar en modo local."
        st.markdown(f'<p style="color:#4a5a72;font-size:13px;">{msg}</p>',
                    unsafe_allow_html=True)
    else:
        html = ""
        for ev in st.session_state.historial[:12]:
            dot  = "event-dot-ocu" if ev["estado"] == "OCUPADO" else "event-dot-lib"
            ec   = "ev-ocu"        if ev["estado"] == "OCUPADO" else "ev-lib"
            ico  = "🔒"            if ev["estado"] == "OCUPADO" else "🔓"
            orig = ev.get("origen", "LOCAL")
            orig_cls = {
                "LOCAL":    "ev-local",
                "REMOTO":   "ev-remoto",
                "SERVIDOR": "ev-server",
            }.get(orig, "ev-local")
            html += f"""
            <div class="event-row">
                <div class="{dot}"></div>
                <div class="event-estado {ec}">{ico} {ev['estado']}</div>
                <div class="event-info">Locker <b>{ev['locker']}</b> — {ev['codigo']}</div>
                <span class="event-origen {orig_cls}">{orig}</span>
                <div class="event-hora">{ev['hora']}</div>
            </div>"""
        st.markdown(html, unsafe_allow_html=True)

with rcol:
    st.markdown('<p class="sec-title">📊 Ocupación</p>', unsafe_allow_html=True)
    pct   = int((ocupados_cnt / TOTAL_LOCKERS) * 100)
    color = "#f87171" if pct > 70 else "#fbbf24" if pct > 40 else "#34d399"
    st.markdown(f"""
    <div style="background:#0c1523;border:1px solid rgba(255,255,255,0.07);
                border-radius:14px;padding:22px;">
        <div style="font-size:46px;font-weight:700;font-family:'Space Mono',monospace;
                    color:{color};text-align:center;">{pct}%</div>
        <div style="font-size:11px;color:#4a5a72;text-align:center;margin-bottom:14px;
                    text-transform:uppercase;letter-spacing:0.08em;">Ocupación</div>
        <div style="background:#1a2535;border-radius:6px;height:7px;overflow:hidden;">
            <div style="background:{color};height:100%;width:{pct}%;border-radius:6px;"></div>
        </div>
        <div style="display:flex;justify-content:space-between;margin-top:14px;font-size:13px;">
            <span style="color:#34d399;"><b>{libres_cnt}</b> libres</span>
            <span style="color:#f87171;"><b>{ocupados_cnt}</b> ocupados</span>
        </div>
    </div>""", unsafe_allow_html=True)

    if mapa:
        st.markdown('<p class="sec-title" style="margin-top:16px;">En uso</p>',
                    unsafe_allow_html=True)
        for lok, cod in sorted(mapa.items(), key=lambda x: int(x[0])):
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;align-items:center;
                        padding:7px 12px;background:#0c1523;border-radius:8px;
                        margin-bottom:5px;border:1px solid rgba(248,113,113,0.15);">
                <span style="font-family:'Space Mono',monospace;color:#f87171;font-size:13px;">#{lok}</span>
                <span style="color:#94a3b8;font-size:12px;font-family:'Space Mono',monospace;">{cod}</span>
            </div>""", unsafe_allow_html=True)

# ── HISTORIAL COMPLETO ───────────────────────────────────────
if st.session_state.historial:
    st.markdown("---")
    st.markdown('<p class="sec-title">📋 Historial completo</p>', unsafe_allow_html=True)
    import pandas as pd
    df = pd.DataFrame(st.session_state.historial)[["hora","estado","locker","codigo","origen"]]
    df.columns = ["Hora","Estado","Locker","Código","Origen"]
    st.dataframe(df, use_container_width=True, hide_index=True)

# ── AUTOREFRESH (solo lectura, sin acciones automáticas) ─────
# Solo refresca si hay conexión activa, para mostrar eventos remotos.
# NO genera ni ejecuta acciones automáticas.
if dll_conectada() or dll_corriendo():
    time.sleep(1)
    st.rerun()
