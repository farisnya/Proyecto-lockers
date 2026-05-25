import socket
import threading
import time
import json
import sys
import os
import argparse
import queue
import hashlib
import secrets
from datetime import datetime
from flask import Flask, Response, request, jsonify

# ── Configuración ───────────────────────────────────────────
SERVER_IP    = "127.0.0.1"
SERVER_PORT  = 8888
WEB_HOST     = "0.0.0.0"
WEB_PORT     = 5000
ARCHIVO_USUARIOS = "usuarios_web.json"
MAX_HISTORIAL    = 200

# ── Estado global ────────────────────────────────────────────
state_lock   = threading.Lock()
lockers      = {str(i): {"ocupado": False, "codigo": "", "usuario": "", "hora": ""}
                for i in range(1, 11)}
historial    = []          # lista de dicts {accion, locker, codigo, usuario, ip, hora}
sse_clients  = []
sse_lock     = threading.Lock()

# Sesiones web: token_web → {usuario, srv_token}
web_sessions = {}
ws_lock      = threading.Lock()

# Usuarios web: nombre → hash
web_users    = {}
wu_lock      = threading.Lock()

# Socket al servidor C++
srv_sock      = None
srv_lock      = threading.Lock()
srv_connected = False
reconectar_srv = True

app = Flask(__name__, static_folder=None)

# ── Utilidades ───────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def hash_pass(pwd: str) -> str:
    """SHA-256 simple para persistencia local."""
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()

# ── Persistencia de usuarios ─────────────────────────────────
def cargar_usuarios():
    global web_users
    if not os.path.exists(ARCHIVO_USUARIOS):
        log(f"{ARCHIVO_USUARIOS} no encontrado, empezando con usuarios vacíos.")
        return
    try:
        with open(ARCHIVO_USUARIOS, "r", encoding="utf-8") as f:
            data = json.load(f)
        with wu_lock:
            web_users = {u["nombre"]: u["hash"] for u in data.get("usuarios", [])}
        log(f"Cargados {len(web_users)} usuarios desde {ARCHIVO_USUARIOS}")
    except Exception as e:
        log(f"Error cargando usuarios: {e}")

def guardar_usuarios():
    try:
        with wu_lock:
            data = {"usuarios": [{"nombre": n, "hash": h} for n, h in web_users.items()]}
        with open(ARCHIVO_USUARIOS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"Usuarios guardados ({len(data['usuarios'])} registros)")
    except Exception as e:
        log(f"Error guardando usuarios: {e}")

def asegurar_admin():
    with wu_lock:
        if "admin" not in web_users:
            web_users["admin"] = hash_pass("admin123")
            log("Usuario 'admin' creado (pass: admin123)")
    guardar_usuarios()

# ── SSE broadcast ────────────────────────────────────────────
def broadcast_sse(data: dict):
    msg = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    with sse_lock:
        dead = []
        for q in sse_clients:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)

# ── Procesar líneas del servidor C++ ─────────────────────────
def procesar_linea_servidor(linea: str):
    linea = linea.strip()
    if not linea or linea == "PONG":
        return

    def campos(prefix: str, body: str) -> dict:
        """Parsea key:val|key:val ignorando el primer token."""
        result = {}
        for part in body.split("|"):
            if ":" in part:
                k, v = part.split(":", 1)
                result[k.strip()] = v.strip()
        return result

    # AUTH_OK — actualizar srv_token de la sesión correspondiente
    if linea.startswith("AUTH_OK|"):
        c = campos("AUTH_OK", linea[8:])
        tok_srv = c.get("Token", "")
        usr = c.get("Usuario", "")
        if tok_srv and usr:
            with ws_lock:
                # Buscar sesión web de este usuario y actualizar srv_token
                for tok_web, ses in web_sessions.items():
                    if ses["usuario"] == usr and ses.get("srv_token", "") == "PENDIENTE":
                        ses["srv_token"] = tok_srv
                        log(f"srv_token actualizado para {usr}: {tok_srv}")
                        break
        return

    # SNAP|Locker:N|Codigo:C|Usuario:U|Hora:H
    if linea.startswith("SNAP|"):
        c = campos("SNAP", linea[5:])
        lok = c.get("Locker", "")
        if lok and c.get("Codigo", ""):
            with state_lock:
                lockers[lok] = {
                    "ocupado": True,
                    "codigo":  c.get("Codigo", ""),
                    "usuario": c.get("Usuario", ""),
                    "hora":    c.get("Hora", ""),
                }
            broadcast_sse({"tipo": "locker", "locker": lok, "ocupado": True,
                           "codigo": c.get("Codigo",""), "usuario": c.get("Usuario",""),
                           "hora": c.get("Hora","")})
        return

    # HIST|Accion:A|Locker:N|Codigo:C|Usuario:U|IP:I|Hora:H
    if linea.startswith("HIST|"):
        c = campos("HIST", linea[5:])
        ev = {
            "accion":  c.get("Accion", ""),
            "locker":  c.get("Locker", ""),
            "codigo":  c.get("Codigo", ""),
            "usuario": c.get("Usuario", ""),
            "ip":      c.get("IP", ""),
            "hora":    c.get("Hora", ""),
        }
        with state_lock:
            dup = any(h["locker"] == ev["locker"] and h["hora"] == ev["hora"]
                      for h in historial[:10])
            if not dup:
                historial.insert(0, ev)
                if len(historial) > MAX_HISTORIAL:
                    historial.pop()
        return

    # EVENT|Accion:OCUPADO|Locker:N|Codigo:C|Usuario:U|IP:I|Hora:H
    if linea.startswith("EVENT|"):
        c = campos("EVENT", linea[6:])
        accion = c.get("Accion", "")
        lok    = c.get("Locker", "")
        cod    = c.get("Codigo", "")
        usr    = c.get("Usuario", "")
        ip_ev  = c.get("IP", "")
        hora   = c.get("Hora", "")
        if not lok:
            return
        ocupado = (accion == "OCUPADO")
        with state_lock:
            lockers[lok] = {
                "ocupado": ocupado,
                "codigo":  cod if ocupado else "",
                "usuario": usr if ocupado else "",
                "hora":    hora,
            }
            ev = {"accion": accion, "locker": lok, "codigo": cod,
                  "usuario": usr, "ip": ip_ev, "hora": hora}
            historial.insert(0, ev)
            if len(historial) > MAX_HISTORIAL:
                historial.pop()
        broadcast_sse({"tipo": "evento", "accion": accion, "locker": lok,
                       "codigo": cod, "usuario": usr, "ip": ip_ev, "hora": hora})
        return

    # Ignorar silenciosamente: REGISTER_OK/FAIL, LOGOUT_OK, PONG, ERROR:*
    # (el web server no necesita procesarlos, ya respondió el servidor C++)

# ── Hilo de conexión al servidor C++ ─────────────────────────
def hilo_servidor():
    global srv_sock, srv_connected

    while reconectar_srv:
        try:
            log(f"Conectando al servidor C++ {SERVER_IP}:{SERVER_PORT}...")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(8)
            s.connect((SERVER_IP, SERVER_PORT))
            s.settimeout(None)

            with srv_lock:
                srv_sock = s
                srv_connected = True

            log("Conectado al servidor C++ ✓")
            broadcast_sse({"tipo": "conexion", "estado": "conectado"})

            buf = ""
            while True:
                data = s.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8", errors="ignore")
                while "\n" in buf:
                    linea, buf = buf.split("\n", 1)
                    procesar_linea_servidor(linea)

        except Exception as e:
            log(f"Servidor C++ no disponible: {e}")
        finally:
            with srv_lock:
                srv_sock = None
                srv_connected = False
            broadcast_sse({"tipo": "conexion", "estado": "desconectado"})

        if reconectar_srv:
            log("Reintentando en 4 segundos...")
            time.sleep(4)

def enviar_servidor(msg: str) -> bool:
    with srv_lock:
        if srv_sock is None:
            return False
        try:
            srv_sock.sendall((msg + "\n").encode("utf-8"))
            return True
        except Exception as e:
            log(f"Error enviando al servidor C++: {e}")
            return False

# ── Autenticación web ─────────────────────────────────────────
def login_web(usr: str, pwd: str) -> dict:
    with wu_lock:
        if usr not in web_users:
            return {"ok": False, "error": "Usuario no encontrado"}
        if web_users[usr] != hash_pass(pwd):
            return {"ok": False, "error": "Contraseña incorrecta"}

    tok_web = secrets.token_hex(20)
    with ws_lock:
        web_sessions[tok_web] = {"usuario": usr, "srv_token": "PENDIENTE"}

    # Enviar LOGIN al servidor C++ para obtener srv_token
    # La respuesta AUTH_OK actualizará srv_token en procesar_linea_servidor
    enviado = enviar_servidor(f"LOGIN|Usuario:{usr}|Pass:{pwd}")
    if not enviado:
        # Modo local: generar token local
        with ws_lock:
            web_sessions[tok_web]["srv_token"] = secrets.token_hex(16)

    log(f"LOGIN: {usr} → tok_web={tok_web[:8]}...")
    return {"ok": True, "token": tok_web, "usuario": usr}

def register_web(usr: str, pwd: str) -> dict:
    if len(usr) < 3:
        return {"ok": False, "error": "Usuario muy corto (mín 3 caracteres)"}
    if len(pwd) < 4:
        return {"ok": False, "error": "Contraseña muy corta (mín 4 caracteres)"}

    with wu_lock:
        if usr in web_users:
            return {"ok": False, "error": "Usuario ya existe"}
        web_users[usr] = hash_pass(pwd)

    guardar_usuarios()
    # También registrar en servidor C++
    enviar_servidor(f"REGISTER|Usuario:{usr}|Pass:{pwd}")
    log(f"REGISTER: {usr}")
    return {"ok": True}

# ── HTML completo ─────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>SmartLocker v4</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#05080f; --bg2:#0a1020; --bg3:#0f1830;
  --border:rgba(255,255,255,0.07);
  --green:#22d3a5; --red:#f4694b; --amber:#f59e0b; --blue:#60a5fa;
  --text:#e2e8f0; --muted:#4a5568;
  --font:'Plus Jakarta Sans',sans-serif; --mono:'Space Mono',monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh}

/* ── AUTH ── */
#auth-screen{display:flex;align-items:center;justify-content:center;min-height:100vh;
  background-image:radial-gradient(ellipse at 20% 50%,rgba(34,211,165,.06) 0,transparent 50%),
                   radial-gradient(ellipse at 80% 20%,rgba(96,165,250,.06) 0,transparent 50%)}
.auth-card{background:var(--bg2);border:1px solid var(--border);border-radius:20px;
  padding:40px;width:100%;max-width:400px;box-shadow:0 24px 64px rgba(0,0,0,.5)}
.auth-logo{text-align:center;margin-bottom:28px}
.auth-logo .icon{font-size:48px}
.auth-logo h1{font-size:24px;font-weight:700;color:var(--green);font-family:var(--mono);margin-top:8px}
.auth-logo p{font-size:12px;color:var(--muted);margin-top:4px}
.tabs{display:flex;background:var(--bg3);border-radius:10px;padding:4px;margin-bottom:20px}
.tab-btn{flex:1;padding:9px;border:none;background:transparent;color:var(--muted);
  font-family:var(--font);font-size:13px;font-weight:600;border-radius:7px;cursor:pointer;transition:all .2s}
.tab-btn.active{background:var(--bg2);color:var(--text)}
.field{margin-bottom:14px}
.field label{display:block;font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted);margin-bottom:6px}
.field input{width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:10px;padding:11px 14px;font-family:var(--font);font-size:14px;
  color:var(--text);outline:none;transition:border .2s}
.field input:focus{border-color:var(--green)}
.btn-primary{width:100%;padding:13px;background:var(--green);border:none;
  border-radius:10px;color:#000;font-family:var(--font);font-size:14px;
  font-weight:700;cursor:pointer;transition:opacity .2s;margin-top:4px}
.btn-primary:hover{opacity:.85}
.btn-primary:disabled{opacity:.4;cursor:default}
.auth-msg{text-align:center;font-size:13px;margin-top:10px;min-height:18px}
.auth-msg.error{color:var(--red)}
.auth-msg.ok{color:var(--green)}

/* ── APP ── */
/* #app visibility controlled via inline style */
.topbar{display:flex;align-items:center;justify-content:space-between;
  padding:14px 24px;border-bottom:1px solid var(--border);background:var(--bg2);
  position:sticky;top:0;z-index:100}
.topbar-left{display:flex;align-items:center;gap:14px}
.topbar-logo{font-size:18px;font-weight:700;color:var(--green);font-family:var(--mono)}
.conn-badge{display:flex;align-items:center;gap:6px;background:var(--bg3);
  border:1px solid var(--border);border-radius:20px;padding:5px 12px}
.conn-dot{width:7px;height:7px;border-radius:50%}
.conn-dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
.conn-dot.off{background:var(--red)}
.conn-label{font-size:11px;color:var(--muted)}
.user-pill{display:flex;align-items:center;gap:8px}
.user-name{font-size:13px;font-weight:600;color:var(--green)}
.btn-logout{background:none;border:1px solid var(--border);border-radius:8px;
  padding:5px 11px;font-size:12px;color:var(--muted);cursor:pointer;
  font-family:var(--font);transition:all .2s}
.btn-logout:hover{border-color:var(--red);color:var(--red)}

.content{max-width:1200px;margin:0 auto;padding:24px}

/* ── METRICS ── */
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}
@media(max-width:600px){.metrics{grid-template-columns:repeat(2,1fr)}}
.metric{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:18px}
.metric-val{font-size:34px;font-weight:700;font-family:var(--mono);line-height:1}
.metric-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-top:4px}
.mv-r{color:var(--red)} .mv-g{color:var(--green)} .mv-b{color:var(--blue)} .mv-a{color:var(--amber)}

/* ── LOCKERS ── */
.section-title{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.1em;color:var(--muted);margin-bottom:12px}
.locker-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:24px}
@media(max-width:600px){.locker-grid{grid-template-columns:repeat(2,1fr)}}
.locker-card{border-radius:14px;padding:16px;cursor:pointer;transition:all .2s;
  display:flex;flex-direction:column;align-items:center;gap:5px;min-height:110px;
  justify-content:center}
.locker-card:hover{transform:translateY(-2px)}
.lk-libre{background:linear-gradient(135deg,#03120a,#051a10);border:1.5px solid rgba(34,211,165,.2)}
.lk-libre:hover{border-color:rgba(34,211,165,.5)}
.lk-ocup{background:linear-gradient(135deg,#120303,#1a0505);border:1.5px solid rgba(244,105,75,.3)}
.lk-ocup:hover{border-color:rgba(244,105,75,.6)}
.lk-icon{font-size:20px}
.lk-num{font-family:var(--mono);font-size:22px;font-weight:700}
.lk-num-libre{color:var(--green)} .lk-num-ocup{color:var(--red)}
.lk-tag{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em}
.lk-tag-libre{color:rgba(34,211,165,.4)} .lk-tag-ocup{color:rgba(244,105,75,.5)}
.lk-code{font-size:11px;color:#94a3b8;font-family:var(--mono)}
.lk-user{font-size:10px;color:var(--muted)}

/* ── MODAL ── */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);
  display:none;align-items:center;justify-content:center;z-index:1000;backdrop-filter:blur(4px)}
.modal-overlay.open{display:flex}
.modal{background:var(--bg2);border:1px solid var(--border);border-radius:20px;
  padding:32px;width:100%;max-width:360px}
.modal h3{font-size:17px;font-weight:700;margin-bottom:4px}
.modal p{font-size:13px;color:var(--muted);margin-bottom:16px}
.modal-num{font-family:var(--mono);font-size:42px;font-weight:700;text-align:center;margin-bottom:14px}
.modal-owner{font-size:12px;color:var(--muted);text-align:center;margin-bottom:16px;
  background:var(--bg3);border-radius:8px;padding:8px}
.modal-btns{display:flex;gap:10px;margin-top:18px}
.btn-sec{flex:1;padding:11px;background:var(--bg3);border:1px solid var(--border);
  border-radius:10px;color:var(--text);font-family:var(--font);font-size:13px;font-weight:600;cursor:pointer}
.btn-ocu{flex:1;padding:11px;background:rgba(34,211,165,.12);border:1px solid rgba(34,211,165,.3);
  border-radius:10px;color:var(--green);font-family:var(--font);font-size:13px;font-weight:600;cursor:pointer}
.btn-lib{flex:1;padding:11px;background:rgba(244,105,75,.12);border:1px solid rgba(244,105,75,.3);
  border-radius:10px;color:var(--red);font-family:var(--font);font-size:13px;font-weight:600;cursor:pointer}
.modal-msg{text-align:center;font-size:13px;margin-top:10px;min-height:18px}
.modal-msg.error{color:var(--red)} .modal-msg.ok{color:var(--green)}

/* ── BOTTOM GRID ── */
.bottom-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:800px){.bottom-grid{grid-template-columns:1fr}}
.panel{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:20px}
.panel-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;
  color:var(--muted);margin-bottom:14px;display:flex;align-items:center;gap:8px}
.panel-tabs{display:flex;gap:6px;margin-bottom:14px}
.ptab{padding:5px 12px;border:1px solid var(--border);border-radius:20px;
  font-size:11px;font-weight:600;cursor:pointer;background:transparent;
  color:var(--muted);font-family:var(--font);transition:all .2s}
.ptab.active{background:var(--green);color:#000;border-color:var(--green)}

/* ── HISTORIAL ── */
.hist-list{display:flex;flex-direction:column;gap:6px;max-height:340px;overflow-y:auto}
.hist-list::-webkit-scrollbar{width:4px}
.hist-list::-webkit-scrollbar-thumb{background:var(--bg3);border-radius:2px}
.hist-item{display:flex;align-items:center;gap:8px;padding:9px 12px;
  background:var(--bg3);border:1px solid var(--border);border-radius:9px;transition:all .3s}
.hist-item.new-event{background:#0a1f14;border-color:rgba(34,211,165,.3)}
.hist-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.hd-o{background:var(--red)} .hd-l{background:var(--green)}
.hist-accion{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;min-width:52px}
.ha-o{color:var(--red)} .ha-l{color:var(--green)}
.hist-info{flex:1;font-size:12px;color:#cbd5e1}
.hist-info b{color:var(--text)}
.hist-user{font-size:10px;color:var(--muted);white-space:nowrap}
.hist-hora{font-family:var(--mono);font-size:10px;color:var(--muted);white-space:nowrap}
.empty{text-align:center;color:var(--muted);font-size:13px;padding:24px}

/* ── OCUPACIÓN ── */
.ocu-pct{font-size:48px;font-weight:700;font-family:var(--mono);text-align:center;line-height:1}
.ocu-sub{font-size:10px;text-transform:uppercase;letter-spacing:.1em;
  color:var(--muted);text-align:center;margin-bottom:14px}
.bar-bg{background:var(--bg3);border-radius:6px;height:8px;overflow:hidden;margin-bottom:14px}
.bar-fill{height:100%;border-radius:6px;transition:width .5s ease}
.ocu-detail{display:flex;justify-content:space-around}
.ocu-d{text-align:center}
.ocu-d .val{font-size:22px;font-weight:700;font-family:var(--mono)}
.ocu-d .lbl{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}

/* ── TOAST ── */
.toast{position:fixed;bottom:24px;right:24px;background:var(--bg2);
  border:1px solid var(--border);border-radius:12px;padding:12px 18px;
  font-size:13px;transform:translateY(80px);opacity:0;transition:all .3s;z-index:2000;
  max-width:320px;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.toast.show{transform:translateY(0);opacity:1}
</style>
</head>
<body>

<!-- ══ PANTALLA AUTH ══════════════════════════════════════ -->
<div id="auth-screen">
  <div class="auth-card">
    <div class="auth-logo">
      <div class="icon">🔐</div>
      <h1>SMARTLOCKER</h1>
      <p>Sistema de gestión de lockers v4</p>
    </div>

    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('login')">Iniciar sesión</button>
      <button class="tab-btn"        onclick="switchTab('register')">Registrarse</button>
    </div>

    <!-- LOGIN -->
    <div id="tab-login">
      <div class="field">
        <label>Usuario</label>
        <input id="l-user" type="text" placeholder="Tu nombre de usuario" autocomplete="username">
      </div>
      <div class="field">
        <label>Contraseña</label>
        <input id="l-pass" type="password" placeholder="Tu contraseña" autocomplete="current-password">
      </div>
      <button class="btn-primary" onclick="doLogin()">Entrar →</button>
      <div class="auth-msg" id="l-msg"></div>
    </div>

    <!-- REGISTER -->
    <div id="tab-register" style="display:none">
      <div class="field">
        <label>Usuario <span style="color:var(--muted);font-weight:400">(mín 3 caracteres)</span></label>
        <input id="r-user" type="text" placeholder="Elige un nombre de usuario" autocomplete="username">
      </div>
      <div class="field">
        <label>Contraseña <span style="color:var(--muted);font-weight:400">(mín 4 caracteres)</span></label>
        <input id="r-pass" type="password" placeholder="Elige una contraseña" autocomplete="new-password">
      </div>
      <button class="btn-primary" onclick="doRegister()">Crear cuenta →</button>
      <div class="auth-msg" id="r-msg"></div>
    </div>
  </div>
</div>

<!-- ══ APP PRINCIPAL ══════════════════════════════════════ -->
<div id="app" style="display:none">
  <div class="topbar">
    <div class="topbar-left">
      <span class="topbar-logo">🔒 SMARTLOCKER</span>
      <div class="conn-badge">
        <div class="conn-dot off" id="conn-dot"></div>
        <span class="conn-label" id="conn-label">Conectando…</span>
      </div>
    </div>
    <div class="user-pill">
      <span class="user-name">👤 <span id="user-name-display"></span></span>
      <button class="btn-logout" onclick="doLogout()">Salir</button>
    </div>
  </div>

  <div class="content">

    <!-- Métricas -->
    <div class="metrics">
      <div class="metric"><div class="metric-val mv-r" id="m-ocu">0</div><div class="metric-lbl">Ocupados</div></div>
      <div class="metric"><div class="metric-val mv-g" id="m-lib">10</div><div class="metric-lbl">Libres</div></div>
      <div class="metric"><div class="metric-val mv-b" id="m-ev">0</div><div class="metric-lbl">Eventos hoy</div></div>
      <div class="metric"><div class="metric-val mv-a" id="m-usr">1</div><div class="metric-lbl">Usuarios activos</div></div>
    </div>

    <!-- Grid de lockers -->
    <div class="section-title">⬜ Estado de lockers</div>
    <div class="locker-grid" id="locker-grid"></div>

    <!-- Panel inferior -->
    <div class="bottom-grid">

      <!-- Historial -->
      <div class="panel">
        <div class="panel-title">📋 Historial de movimientos</div>
        <div class="panel-tabs">
          <button class="ptab active" onclick="switchHistTab('global')">Global</button>
          <button class="ptab"        onclick="switchHistTab('mio')">Mi historial</button>
        </div>
        <div class="hist-list" id="hist-list"></div>
      </div>

      <!-- Ocupación -->
      <div class="panel">
        <div class="panel-title">📊 Ocupación actual</div>
        <div class="ocu-pct" id="ocu-pct">0%</div>
        <div class="ocu-sub">de capacidad usada</div>
        <div class="bar-bg"><div class="bar-fill" id="bar-fill" style="width:0%;background:var(--green)"></div></div>
        <div class="ocu-detail">
          <div class="ocu-d">
            <div class="val mv-r" id="cnt-ocu">0</div>
            <div class="lbl">Ocupados</div>
          </div>
          <div class="ocu-d">
            <div class="val mv-g" id="cnt-lib">10</div>
            <div class="lbl">Libres</div>
          </div>
        </div>
      </div>

    </div>
  </div>
</div>

<!-- ══ MODAL LOCKER ══════════════════════════════════════ -->
<div class="modal-overlay" id="modal" onclick="closeModal(event)">
  <div class="modal">
    <h3 id="modal-title">Locker</h3>
    <p  id="modal-sub"></p>
    <div class="modal-num" id="modal-num">#01</div>
    <div class="modal-owner" id="modal-owner" style="display:none"></div>
    <div id="field-codigo" class="field">
      <label>Código de arrendamiento</label>
      <input id="modal-codigo" type="text" placeholder="Ej: ABC123" maxlength="20">
    </div>
    <div class="modal-btns" id="modal-btns"></div>
    <div class="modal-msg" id="modal-msg"></div>
  </div>
</div>

<!-- ══ TOAST ══════════════════════════════════════════════ -->
<div class="toast" id="toast"></div>

<script>
// ── Capturar errores JS silenciosos ────────────────────────
window.onerror = function(msg, src, line, col, err) {
  console.error("[SmartLocker Error]", msg, "line:" + line, err);
  // Mostrar error visible si el usuario ve pantalla negra
  const app = document.getElementById("app");
  const auth = document.getElementById("auth-screen");
  if (app && app.style.display === "none" && auth && auth.style.display === "none") {
    document.body.innerHTML += '<div style="position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#f4694b;color:#000;padding:12px 20px;border-radius:8px;z-index:9999;font-family:monospace">Error JS: ' + msg + ' (línea ' + line + ')</div>';
  }
};

// ── Estado local ─────────────────────────────────────────────
let lockers   = {};
let historial = [];
let token     = "";
let usuario   = "";
let modalLocker = 0;
let histTab   = "global";

// Inicializar lockers vacíos
for (let i = 1; i <= 10; i++)
  lockers[String(i)] = {ocupado:false, codigo:"", usuario:"", hora:""};

// ── AUTH ─────────────────────────────────────────────────────
function switchTab(t) {
  document.getElementById("tab-login").style.display    = t === "login"    ? "" : "none";
  document.getElementById("tab-register").style.display = t === "register" ? "" : "none";
  document.querySelectorAll(".tab-btn").forEach((b,i) =>
    b.classList.toggle("active", (t === "login") ? i === 0 : i === 1));
}

async function doLogin() {
  const usr = document.getElementById("l-user").value.trim();
  const pwd = document.getElementById("l-pass").value;
  const msg = document.getElementById("l-msg");
  if (!usr || !pwd) { msg.textContent = "Completa todos los campos"; msg.className = "auth-msg error"; return; }
  msg.textContent = "Verificando…"; msg.className = "auth-msg";
  const r = await fetch("/api/login", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({usuario: usr, password: pwd})
  });
  const d = await r.json();
  if (d.ok) {
    token   = d.token;
    usuario = d.usuario;
    msg.textContent = "";
    mostrarApp();
    cargarEstado().catch(e => console.error("cargarEstado:", e));
    try { conectarSSE(); } catch(e) { console.error("conectarSSE:", e); }
  } else {
    msg.textContent = "❌ " + d.error;
    msg.className = "auth-msg error";
  }
}

async function doRegister() {
  const usr = document.getElementById("r-user").value.trim();
  const pwd = document.getElementById("r-pass").value;
  const msg = document.getElementById("r-msg");
  if (!usr || !pwd) { msg.textContent = "Completa todos los campos"; msg.className = "auth-msg error"; return; }
  msg.textContent = "Creando cuenta…"; msg.className = "auth-msg";
  const r = await fetch("/api/register", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({usuario: usr, password: pwd})
  });
  const d = await r.json();
  if (d.ok) {
    msg.textContent = "✅ Cuenta creada. Ahora inicia sesión.";
    msg.className = "auth-msg ok";
    document.getElementById("r-user").value = "";
    document.getElementById("r-pass").value = "";
    setTimeout(() => switchTab("login"), 1500);
  } else {
    msg.textContent = "❌ " + d.error;
    msg.className = "auth-msg error";
  }
}

async function doLogout() {
  await fetch("/api/logout", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({token})
  });
  token = ""; usuario = "";
  document.getElementById("app").style.display          = "none";
  document.getElementById("auth-screen").style.display  = "flex";
  document.getElementById("l-user").value = "";
  document.getElementById("l-pass").value = "";
}

function mostrarApp() {
  document.getElementById("auth-screen").style.display = "none";
  document.getElementById("app").style.display         = "block"; // remove inline none
  document.getElementById("user-name-display").textContent = usuario;
  renderAll(); // renderizar inmediatamente con estado local (10 lockers libres)
}

// ── Estado inicial ────────────────────────────────────────────
async function cargarEstado() {
  try {
    const r = await fetch("/api/state");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    lockers   = d.lockers   || lockers;
    historial = d.historial || [];
    renderAll();
  } catch(e) {
    console.error("Error cargando estado:", e);
    renderAll(); // mostrar estado local aunque el servidor no responda
  }
}

// ── SSE ───────────────────────────────────────────────────────
let sseRetries = 0;
function conectarSSE() {
  const es = new EventSource("/api/events");
  es.onopen = () => { sseRetries = 0; };
  es.onmessage = e => {
    try { manejarEvento(JSON.parse(e.data)); } catch (_) {}
  };
  es.onerror = () => {
    es.close();
    sseRetries++;
    const delay = Math.min(1000 * Math.pow(1.5, sseRetries), 30000);
    setTimeout(conectarSSE, delay);
  };
}

function manejarEvento(data) {
  if (data.tipo === "conexion") {
    setConnected(data.estado === "conectado");
    return;
  }
  if (data.tipo === "ping") return;

  if (data.tipo === "locker") {
    lockers[data.locker] = {ocupado:data.ocupado, codigo:data.codigo,
                             usuario:data.usuario, hora:data.hora};
    renderLockers(); updateMetrics();
    return;
  }
  if (data.tipo === "evento") {
    const ocu = data.accion === "OCUPADO";
    lockers[data.locker] = {
      ocupado: ocu, codigo: ocu ? data.codigo : "",
      usuario: ocu ? data.usuario : "", hora: data.hora
    };
    historial.unshift({accion:data.accion, locker:data.locker, codigo:data.codigo,
                       usuario:data.usuario, ip:data.ip, hora:data.hora});
    if (historial.length > 200) historial.pop();
    renderAll();
    const emoji = ocu ? "🔒" : "🔓";
    showToast(`${emoji} Locker #${data.locker} ${ocu?"arrendado":"liberado"} por ${data.usuario}`);
    return;
  }
}

function setConnected(on) {
  document.getElementById("conn-dot").className = "conn-dot " + (on ? "on" : "off");
  document.getElementById("conn-label").textContent = on ? "Servidor conectado" : "Sin servidor";
}

// ── Render ────────────────────────────────────────────────────
function renderAll() { renderLockers(); renderHistorial(); updateMetrics(); }

function renderLockers() {
  const g = document.getElementById("locker-grid");
  g.innerHTML = "";
  for (let i = 1; i <= 10; i++) {
    const lok = lockers[String(i)] || {ocupado:false};
    const div = document.createElement("div");
    div.className = "locker-card " + (lok.ocupado ? "lk-ocup" : "lk-libre");
    div.onclick   = () => openModal(i);
    const cod = lok.codigo ? (lok.codigo.length > 8 ? lok.codigo.slice(0,8)+"…" : lok.codigo) : "";
    div.innerHTML = `
      <div class="lk-icon">${lok.ocupado ? "🔒" : "🔓"}</div>
      <div class="lk-num ${lok.ocupado?"lk-num-ocup":"lk-num-libre"}">${String(i).padStart(2,"0")}</div>
      <div class="lk-tag ${lok.ocupado?"lk-tag-ocup":"lk-tag-libre"}">${lok.ocupado?"OCUPADO":"LIBRE"}</div>
      ${cod ? `<div class="lk-code">${cod}</div>` : ""}
      ${lok.usuario ? `<div class="lk-user">👤 ${lok.usuario}</div>` : ""}
    `;
    g.appendChild(div);
  }
}

function switchHistTab(t) {
  histTab = t;
  document.querySelectorAll(".ptab").forEach((b,i) =>
    b.classList.toggle("active", (t === "global") ? i === 0 : i === 1));
  renderHistorial();
}

function renderHistorial() {
  const h = document.getElementById("hist-list");
  let lista = historial;
  if (histTab === "mio") lista = historial.filter(ev => ev.usuario === usuario);

  if (!lista.length) {
    h.innerHTML = '<div class="empty">' +
      (histTab === "mio" ? "Aún no tienes movimientos." : "Sin eventos aún.") + "</div>";
    return;
  }
  h.innerHTML = lista.slice(0, 40).map((ev, idx) => `
    <div class="hist-item ${idx===0?"new-event":""}">
      <div class="hist-dot ${ev.accion==="OCUPADO"?"hd-o":"hd-l"}"></div>
      <div class="hist-accion ${ev.accion==="OCUPADO"?"ha-o":"ha-l"}">${ev.accion==="OCUPADO"?"🔒 OCUP":"🔓 LIB"}</div>
      <div class="hist-info">Locker <b>#${ev.locker}</b> · ${ev.codigo}</div>
      <div class="hist-user">👤 ${ev.usuario||"?"}</div>
      <div class="hist-hora">${ev.hora}</div>
    </div>
  `).join("");
}

function updateMetrics() {
  const ocu = Object.values(lockers).filter(l => l.ocupado).length;
  const lib = 10 - ocu;
  const pct = Math.round(ocu / 10 * 100);
  const color = pct > 70 ? "var(--red)" : pct > 40 ? "var(--amber)" : "var(--green)";
  document.getElementById("m-ocu").textContent  = ocu;
  document.getElementById("m-lib").textContent  = lib;
  document.getElementById("m-ev").textContent   = historial.length;
  document.getElementById("ocu-pct").textContent = pct + "%";
  document.getElementById("ocu-pct").style.color = color;
  document.getElementById("bar-fill").style.width      = pct + "%";
  document.getElementById("bar-fill").style.background = color;
  document.getElementById("cnt-ocu").textContent = ocu;
  document.getElementById("cnt-lib").textContent = lib;
  // m-usr: contar usuarios únicos con actividad reciente en historial
  const usrsActivos = new Set(historial.slice(0,50).map(e => e.usuario).filter(Boolean));
  if (usuario) usrsActivos.add(usuario);
  document.getElementById("m-usr").textContent = usrsActivos.size || 1;
}

// ── Modal ─────────────────────────────────────────────────────
function openModal(n) {
  modalLocker = n;
  const lok   = lockers[String(n)] || {ocupado:false};
  const numEl = document.getElementById("modal-num");
  numEl.textContent = "#" + String(n).padStart(2,"0");
  numEl.style.color = lok.ocupado ? "var(--red)" : "var(--green)";
  document.getElementById("modal-msg").textContent = "";
  document.getElementById("modal-msg").className = "modal-msg";

  const ownerEl = document.getElementById("modal-owner");
  const fc      = document.getElementById("field-codigo");
  const btns    = document.getElementById("modal-btns");

  if (lok.ocupado) {
    document.getElementById("modal-title").textContent = "Locker arrendado";
    document.getElementById("modal-sub").textContent   = "Este locker está en uso";
    ownerEl.style.display = "";
    ownerEl.textContent   = `👤 ${lok.usuario || "?"} · Código: ${lok.codigo} · ${lok.hora}`;
    fc.style.display = "none";
    const esAdmin  = (usuario === "admin");
    const esMio    = (lok.usuario === usuario);
    if (esAdmin || esMio) {
      btns.innerHTML = `
        <button class="btn-sec" onclick="closeModal()">Cancelar</button>
        <button class="btn-lib" onclick="doLiberar()">🔓 Devolver locker</button>
      `;
    } else {
      btns.innerHTML = `<button class="btn-sec" style="flex:1" onclick="closeModal()">Cerrar</button>`;
      document.getElementById("modal-msg").textContent =
        "Solo el arrendatario o admin pueden liberar este locker.";
      document.getElementById("modal-msg").className = "modal-msg error";
    }
  } else {
    document.getElementById("modal-title").textContent = "Arrendar locker";
    document.getElementById("modal-sub").textContent   = "Este locker está disponible";
    ownerEl.style.display = "none";
    fc.style.display = "block";
    document.getElementById("modal-codigo").value = "";
    btns.innerHTML = `
      <button class="btn-sec" onclick="closeModal()">Cancelar</button>
      <button class="btn-ocu" onclick="doOcupar()">🔒 Arrendar</button>
    `;
    setTimeout(() => document.getElementById("modal-codigo").focus(), 80);
  }
  document.getElementById("modal").classList.add("open");
}

function closeModal(e) {
  if (!e || e.target === document.getElementById("modal"))
    document.getElementById("modal").classList.remove("open");
}

async function doOcupar() {
  const cod = document.getElementById("modal-codigo").value.trim().toUpperCase();
  const msg = document.getElementById("modal-msg");
  if (!cod) { msg.textContent = "Ingresa un código"; msg.className = "modal-msg error"; return; }
  if (!token) { msg.textContent = "Debes iniciar sesión"; msg.className = "modal-msg error"; return; }
  msg.textContent = "Procesando…"; msg.className = "modal-msg";
  const r = await fetch("/api/ocupar", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({locker: modalLocker, codigo: cod, token})
  });
  const d = await r.json();
  if (d.ok) {
    document.getElementById("modal").classList.remove("open");
  } else {
    msg.textContent = "❌ " + d.error; msg.className = "modal-msg error";
  }
}

async function doLiberar() {
  const lok = lockers[String(modalLocker)];
  if (!lok) return;
  const msg = document.getElementById("modal-msg");
  msg.textContent = "Procesando…"; msg.className = "modal-msg";
  const r = await fetch("/api/liberar", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({locker: modalLocker, codigo: lok.codigo, token})
  });
  const d = await r.json();
  if (d.ok) {
    document.getElementById("modal").classList.remove("open");
  } else {
    msg.textContent = "❌ " + d.error; msg.className = "modal-msg error";
  }
}

// ── Toast ─────────────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3500);
}

// ── Enter / Escape ────────────────────────────────────────────
document.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    const login = document.getElementById("tab-login").style.display !== "none";
    const reg   = document.getElementById("tab-register").style.display !== "none";
    const modal = document.getElementById("modal").classList.contains("open");
    if (login) doLogin();
    else if (reg) doRegister();
    else if (modal) {
      const lok = lockers[String(modalLocker)] || {};
      if (!lok.ocupado) doOcupar();
    }
  }
  if (e.key === "Escape") document.getElementById("modal").classList.remove("open");
});
</script>
</body>
</html>"""

# ── Rutas Flask ──────────────────────────────────────────────
@app.route("/")
def index():
    resp = app.make_response(HTML)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Content-Type"]  = "text/html; charset=utf-8"
    return resp

@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify({"lockers": lockers, "historial": historial[:100]})

@app.route("/api/events")
def api_events():
    q = queue.Queue(maxsize=200)
    with sse_lock:
        sse_clients.append(q)

    def gen():
        # Estado inicial de conexión
        estado = "conectado" if srv_connected else "desconectado"
        yield f"data: {json.dumps({'tipo':'conexion','estado':estado})}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield msg
                except queue.Empty:
                    yield 'data: {"tipo":"ping"}\n\n'
        except GeneratorExit:
            pass
        finally:
            with sse_lock:
                if q in sse_clients:
                    sse_clients.remove(q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.route("/api/login", methods=["POST"])
def api_login():
    d   = request.json or {}
    usr = d.get("usuario", "").strip()
    pwd = d.get("password", "")
    if not usr or not pwd:
        return jsonify({"ok": False, "error": "Datos incompletos"})
    return jsonify(login_web(usr, pwd))

@app.route("/api/register", methods=["POST"])
def api_register():
    d   = request.json or {}
    usr = d.get("usuario", "").strip()
    pwd = d.get("password", "")
    if not usr or not pwd:
        return jsonify({"ok": False, "error": "Datos incompletos"})
    return jsonify(register_web(usr, pwd))

@app.route("/api/logout", methods=["POST"])
def api_logout():
    d   = request.json or {}
    tok = d.get("token", "")
    if tok:
        with ws_lock:
            ses = web_sessions.pop(tok, None)
        if ses and ses.get("srv_token") and ses["srv_token"] != "PENDIENTE":
            enviar_servidor(f"LOGOUT|Token:{ses['srv_token']}")
    return jsonify({"ok": True})

@app.route("/api/ocupar", methods=["POST"])
def api_ocupar():
    d      = request.json or {}
    locker = d.get("locker")
    codigo = d.get("codigo", "").strip().upper()
    tok    = d.get("token", "")

    if not locker or not codigo or not tok:
        return jsonify({"ok": False, "error": "Datos incompletos"})

    with ws_lock:
        ses = web_sessions.get(tok)
    if not ses:
        return jsonify({"ok": False, "error": "No autenticado. Recarga e inicia sesión."})

    # Intentar via servidor C++
    srv_tok = ses.get("srv_token", "")
    if srv_tok and srv_tok != "PENDIENTE" and srv_connected:
        ok = enviar_servidor(f"CMD:OCUPAR|Locker:{locker}|Codigo:{codigo}|Token:{srv_tok}")
        if ok:
            return jsonify({"ok": True})

    # Modo local (sin servidor C++ o token pendiente)
    hora = datetime.now().strftime("%H:%M:%S")
    lok  = str(locker)
    with state_lock:
        if lockers[lok]["ocupado"]:
            return jsonify({"ok": False,
                            "error": f"Locker ya ocupado por {lockers[lok]['codigo']}"})
        lockers[lok] = {"ocupado": True, "codigo": codigo,
                        "usuario": ses["usuario"], "hora": hora}
        ev = {"accion": "OCUPADO", "locker": lok, "codigo": codigo,
              "usuario": ses["usuario"], "ip": "LOCAL", "hora": hora}
        historial.insert(0, ev)
        if len(historial) > MAX_HISTORIAL:
            historial.pop()

    broadcast_sse({"tipo": "evento", "accion": "OCUPADO", "locker": lok,
                   "codigo": codigo, "usuario": ses["usuario"], "ip": "LOCAL", "hora": hora})
    return jsonify({"ok": True})

@app.route("/api/liberar", methods=["POST"])
def api_liberar():
    d      = request.json or {}
    locker = d.get("locker")
    codigo = d.get("codigo", "")
    tok    = d.get("token", "")

    with ws_lock:
        ses = web_sessions.get(tok)
    if not ses:
        return jsonify({"ok": False, "error": "No autenticado."})

    # Verificar permisos antes de enviar
    lok = str(locker)
    with state_lock:
        estado_lok = lockers.get(lok, {})
    es_admin = (ses["usuario"] == "admin")
    es_mio   = (estado_lok.get("usuario") == ses["usuario"])
    if not es_admin and not es_mio:
        return jsonify({"ok": False, "error": "Solo puedes liberar tus propios lockers."})

    srv_tok = ses.get("srv_token", "")
    if srv_tok and srv_tok != "PENDIENTE" and srv_connected:
        ok = enviar_servidor(f"CMD:LIBERAR|Locker:{locker}|Codigo:{codigo}|Token:{srv_tok}")
        if ok:
            return jsonify({"ok": True})

    # Modo local
    hora = datetime.now().strftime("%H:%M:%S")
    with state_lock:
        if not lockers[lok]["ocupado"]:
            return jsonify({"ok": False, "error": "El locker ya está libre."})
        cod_real = lockers[lok]["codigo"]
        lockers[lok] = {"ocupado": False, "codigo": "", "usuario": "", "hora": ""}
        ev = {"accion": "LIBERADO", "locker": lok, "codigo": cod_real,
              "usuario": ses["usuario"], "ip": "LOCAL", "hora": hora}
        historial.insert(0, ev)
        if len(historial) > MAX_HISTORIAL:
            historial.pop()

    broadcast_sse({"tipo": "evento", "accion": "LIBERADO", "locker": lok,
                   "codigo": codigo, "usuario": ses["usuario"], "ip": "LOCAL", "hora": hora})
    return jsonify({"ok": True})

# ── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SmartLocker Web Server v4")
    parser.add_argument("--host",    default=WEB_HOST,    help="Host web (default: 0.0.0.0)")
    parser.add_argument("--port",    default=WEB_PORT,    type=int, help="Puerto web (default: 5000)")
    parser.add_argument("--server",  default=SERVER_IP,   help="IP servidor C++ (default: 127.0.0.1)")
    parser.add_argument("--sport",   default=SERVER_PORT, type=int, help="Puerto servidor C++ (default: 8888)")
    parser.add_argument("--norecon", action="store_true", help="No reconectar si cae el servidor C++")
    args = parser.parse_args()

    SERVER_IP      = args.server
    SERVER_PORT    = args.sport
    reconectar_srv = not args.norecon

    # Cargar usuarios y asegurar admin
    cargar_usuarios()
    asegurar_admin()

    # Hilo de conexión al servidor C++
    threading.Thread(target=hilo_servidor, daemon=True).start()

    # IP local para mostrar en consola
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    print("=" * 55)
    print("  SmartLocker Web Server v4")
    print(f"  Servidor C++  : {SERVER_IP}:{SERVER_PORT}")
    print(f"  Web local     : http://{local_ip}:{args.port}")
    print(f"  Usuarios BD   : {ARCHIVO_USUARIOS}")
    print(f"  (abre desde cualquier dispositivo del WiFi)")
    print("=" * 55)

    app.run(host=args.host, port=args.port, threaded=True, debug=False)
