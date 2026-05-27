
| Aspecto | Antes | Ahora |
|---|---|---|
| Interfaz | Streamlit (solo un PC) | Web pura (cualquier dispositivo del WiFi) |
| Auth de usuarios | No había | Registro y login completo |
| Actualización real-time | Polling cada 300ms | Server-Sent Events (SSE) — push instantáneo |
| Clientes soportados | PC con Python | Teléfono, tablet, PC — cualquier navegador |
| Protocolo servidor | Solo broadcast | EVENT / SNAP / AUTH + broadcast |
| Sesiones | Token por sesión, 8 horas |  |

---

## Arquitectura

```
                    ┌─────────────────────────────┐
                    │       servidor.exe (C++)      │
                    │   Puerto TCP 8888             │
                    │   Gestiona lockers            │
                    │   Broadcast a todos           │
                    │   Auth usuarios               │
                    └──────────┬──────────────────┘
                               │ TCP 8888
              ┌────────────────┴────────────────────┐
              │                                     │
              ▼                                     ▼
   ┌─────────────────────┐            ┌──────────────────────────┐
   │   web_server.py     │            │  cliente_locker.exe      │
   │   Flask + SSE       │            │  Consola interactiva     │
   │   Puerto HTTP 5000  │            │  o 3 ABC123 → Ocupar     │
   └──────────┬──────────┘            └──────────────────────────┘
              │ HTTP/SSE
    ┌─────────┴──────────────────────────────────────┐
    │          Cualquier dispositivo del WiFi         │
    │                                                 │
    │  Teléfono      Tablet        Otro PC            │
    │  http://IP:5000  (mismo link para todos)        │
    └─────────────────────────────────────────────────┘
```

---

## Instalación y ejecución

### Requisitos

- **g++** con soporte C++17 (MinGW/MSYS2 en Windows)
- **Python 3.8+** con Flask: `pip install flask`
- Todos los dispositivos en la **misma red WiFi**

### Paso 1: Compilar (solo en el PC servidor)

```bat
compilar.bat
```

O manualmente:
```bat
g++ -o servidor.exe servidor.cpp -lws2_32 -std=c++17
g++ -shared -o libreria_lockers.dll libreria_lockers.cpp -lws2_32 -static -std=c++17
```

**Linux:**
```bash
g++ -o servidor servidor.cpp -std=c++17 -lpthread
g++ -shared -fPIC -o libreria_lockers.so libreria_lockers.cpp -std=c++17 -lpthread
```

### Paso 2: Ejecutar el servidor C++

```bat
servidor.exe
```

Verás:
```
Usuario admin creado (pass: admin123)
==========================================
  SMARTLOCKER SERVIDOR v3
  Puerto: 8888
==========================================
```

### Paso 3: Ejecutar el servidor web

En la misma PC del servidor (o cualquier otra PC de la red):

```bat
python web_server.py
```

O especificando la IP del servidor C++ si está en otra PC:
```bat
python web_server.py --server 192.168.1.10 --port 5000
```

Verás:
```
==================================================
  SmartLocker Web Server
  Servidor C++: 127.0.0.1:8888
  Web:          http://192.168.1.X:5000
  (desde cualquier dispositivo del WiFi)
==================================================
```

### Paso 4: Conectarse desde cualquier dispositivo

Abre un navegador en **cualquier teléfono, tablet o PC** de la red:

```
http://192.168.1.X:5000
```

Usa la IP que mostró el web_server.py.

---

## Sistema de usuarios

### Cuenta por defecto
```
Usuario: admin
Password: admin123
```

### Crear cuenta nueva
1. Abrir la web → pestaña "Registrarse"
2. Ingresar usuario (min 3 caracteres) y contraseña (min 4 caracteres)
3. Iniciar sesión

### Características de sesiones
- Token único por sesión
- Duración: 8 horas
- Solo usuarios autenticados pueden ocupar/liberar lockers
- Ver quién ocupó cada locker

---

## Actualización en tiempo real

El sistema usa **Server-Sent Events (SSE)**:

- Cuando cualquier dispositivo ocupa o libera un locker, el servidor hace **broadcast** instantáneo
- **Todos los navegadores** abiertos se actualizan en menos de 100ms
- Sin polling, sin refresh manual — push puro del servidor
- Funciona en WiFi local sin internet

---

## Protocolo de red (servidor C++)

### Cliente → Servidor
```
REGISTER|Usuario:juan|Pass:1234
LOGIN|Usuario:juan|Pass:1234
LOGOUT|Token:abc123def456
CMD:OCUPAR|Locker:3|Codigo:ABC123|Token:abc123def456
CMD:LIBERAR|Locker:3|Codigo:ABC123|Token:abc123def456
PING
```

### Servidor → Clientes
```
REGISTER_OK|Usuario:juan
REGISTER_FAIL|Motivo:Usuario ya existe
AUTH_OK|Token:abc123def456|Usuario:juan
AUTH_FAIL|Motivo:Contraseña incorrecta
SNAP|Locker:3|Codigo:ABC123|Usuario:juan|Hora:10:30:00
HIST|Accion:OCUPADO|Locker:3|Codigo:ABC123|Usuario:juan|IP:192.168.1.5|Hora:10:30:00
EVENT|Accion:OCUPADO|Locker:3|Codigo:ABC123|Usuario:juan|IP:192.168.1.5|Hora:10:30:00
ERROR:LOCKER_OCUPADO|Locker:3|CodigoActual:XYZ|UsuarioActual:maria
ERROR:NO_AUTH|Motivo:Token invalido o expirado
PONG
```

---

## Archivos

| Archivo | Descripción |
|---|---|
| `servidor.cpp` | Servidor C++ v3 con auth, sesiones, broadcast |
| `libreria_lockers.cpp` | DLL C++ cliente (para Streamlit/Python) |
| `libreria_lockers.h` | Headers de la DLL |
| `web_server.py` | **NUEVO** Servidor Flask + SSE (interfaz web) |
| `visualizador.py` | Dashboard Streamlit (versión anterior, sigue funcionando) |
| `cliente_locker.cpp` | Cliente consola C++ |
| `compilar.bat` | Script de compilación Windows |

---

## Modos de operación

### Modo 1: Web completo (recomendado)
Cualquier dispositivo del WiFi puede usar el sistema.
```
servidor.exe  +  python web_server.py
→ Abrir http://IP:5000 en cualquier dispositivo
```

### Modo 2: Streamlit clásico
```
servidor.exe  +  streamlit run visualizador.py
```

### Modo 3: Consola
```
servidor.exe  +  cliente_locker.exe 192.168.x.x 8888
```

### Modo 4: Sin servidor (local)
`web_server.py` funciona solo (sin `servidor.exe`) en modo local. Las operaciones de locker se aplican localmente y se brodacastan a todos los navegadores conectados al web server.

---

## Firewall

Si los dispositivos no se conectan, asegúrate de que:
- **Puerto 8888** (TCP) esté abierto para el servidor C++
- **Puerto 5000** (TCP) esté abierto para el servidor web

En Windows:
```bat
netsh advfirewall firewall add rule name="SmartLocker Server" dir=in action=allow protocol=TCP localport=8888
netsh advfirewall firewall add rule name="SmartLocker Web" dir=in action=allow protocol=TCP localport=5000
```

---

## Notas técnicas

- El servidor C++ maneja múltiples clientes simultáneos (un hilo por cliente)
- El web_server.py puede manejar cientos de navegadores simultáneos con SSE (hilos mínimos)
- El estado se sincroniza siempre desde el servidor C++ como fuente de verdad
- `web_server.py` puede correr en modo standalone sin servidor C++ (modo local)
- La DLL `libreria_lockers.dll` es compatible con el visualizador Streamlit anterior
