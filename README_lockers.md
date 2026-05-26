# Sistema Inteligente de Lockers

Proyecto cliente-servidor que simula la asignación y liberación de lockers
mediante el envío periódico de códigos. Compuesto por **dos procesos independientes**
que se comunican vía socket TCP, más una **librería dinámica C++** consumida por el visualizador Python.

---

## 1. Arquitectura

```
┌─────────────────────────┐              ┌─────────────────────────────────────────┐
│  Proceso 1 (C++)        │              │  Proceso 2 (Python + DLL C++)           │
│  servidor.exe           │              │  visualizador.py  (Streamlit)           │
│                         │  socket TCP  │   │                                     │
│  - Genera placas        │ ──────────▶  │   └──▶ libreria_lockers.dll             │
│  - Cada 2 o 5 segundos  │  puerto 8888 │         - hilo recv() en C++            │
│  - Formato:             │              │         - cola thread-safe               │
│    Codigo|Hora|Locker   │              │         - procesar_dato() en C++        │
│  - Placa repetida       │              │         - mapa codigo→locker            │
│    → libera locker      │              │                                         │
└─────────────────────────┘              └─────────────────────────────────────────┘
         PC-A  (servidor)                           PC-B  (visualizador)
```

| Componente | Lenguaje | Rol |
|---|---|---|
| `servidor.cpp` → `servidor.exe` | C++ | Genera placas aleatorias, abre socket `0.0.0.0:8888`, envía mensajes. |
| `libreria_lockers.cpp` → `libreria_lockers.dll` | C++ | Cliente del socket con hilo interno. Recibe, parsea y administra el estado de lockers. |
| `visualizador.py` | Python 3 + Streamlit | Carga la DLL con `ctypes`, muestra dashboard en tiempo real. |

---

## 2. Cumplimiento de requerimientos

| Requerimiento | Cumplimiento |
|---|---|
| Generador de códigos cada 2 o 5 segundos | `servidor.cpp`: `sleep_for(2s)` o `sleep_for(5s)` aleatoriamente. |
| Dos procesos: cliente y servidor por socket | `servidor.exe` (servidor TCP) + `visualizador.py` vía DLL (cliente TCP). |
| Envío y recepción **en C++** | `send()` en `servidor.cpp`; `recv()` dentro del hilo de `libreria_lockers.dll`. |
| Visualizador con **librería dinámica** | Python carga `libreria_lockers.dll` con `ctypes.CDLL`. |
| Hora y celda en el mensaje | Formato `Codigo:XXX111\|Hora:HH:MM:SS\|Locker:N`. |
| Código repetido = liberar locker | `procesar_dato()` en la DLL usa `std::map<codigo,locker>`; si entra repetido → LIBERADO. |
| **Ejecutable entre PCs** | IP configurable desde el sidebar del dashboard; servidor escucha en `0.0.0.0`. |

---

## 3. Protocolo de mensajes

Texto plano sobre TCP:

```
Codigo:ABC123|Hora:14:35:07|Locker:3
```

| Campo | Descripción |
|---|---|
| `Codigo` | 3 letras + 3 dígitos generados aleatoriamente. |
| `Hora` | Hora local en formato `HH:MM:SS`. |
| `Locker` | Número de celda asignada (1–10, circular). |

Si el mismo `Codigo` llega dos veces → el locker asociado se **libera**.

---

## 4. API de la librería dinámica

Funciones exportadas por `libreria_lockers.dll`:

| Función | Firma | Descripción |
|---|---|---|
| `conectar` | `int conectar(const char* ip, int puerto, int reconectar)` | Lanza hilo interno de lectura. Retorna 0 si OK. |
| `desconectar` | `void desconectar()` | Cierra el socket y detiene el hilo. |
| `esta_conectado` | `int esta_conectado()` | 1 si el socket está activo. |
| `esta_corriendo` | `int esta_corriendo()` | 1 si el hilo está corriendo (incluso reintentando). |
| `hay_mensaje` | `int hay_mensaje()` | 1 si hay mensajes sin leer. |
| `mensajes_pendientes` | `int mensajes_pendientes()` | Cantidad en la cola. |
| `leer_mensaje_crudo` | `const char* leer_mensaje_crudo()` | Saca el mensaje más antiguo de la cola (no bloqueante). |
| `procesar_dato` | `const char* procesar_dato(const char* msg)` | Procesa el mensaje; retorna `"ESTADO\|CODIGO\|LOCKER\|HORA"`. |
| `cantidad_ocupados` | `int cantidad_ocupados()` | Lockers actualmente ocupados. |
| `ultimo_error` | `const char* ultimo_error()` | Último mensaje de estado/error. |

---

## 5. Compilación

**Requisitos:** `g++` (MinGW-w64 en Windows), Python 3.8+

```bat
compilar.bat
```

Equivale a:

```bat
g++ servidor.cpp -o servidor.exe -lws2_32 -static -std=c++17
g++ -shared -o libreria_lockers.dll libreria_lockers.cpp -lws2_32 -static -std=c++17
```

**Linux:**
```bash
g++ servidor.cpp -o servidor -std=c++17
g++ -shared -fPIC -o libreria_lockers.so libreria_lockers.cpp -std=c++17 -lpthread
```

---

## 6. Ejecución

### En la misma PC
```bat
REM Terminal 1
servidor.exe

REM Terminal 2
pip install streamlit pandas
streamlit run visualizador.py
```

### Entre dos PCs (red local)
```
PC-A (servidor):
    servidor.exe
    → anota la IP local (ej: 192.168.1.50)
    → asegúrate de que el puerto 8888 esté abierto en el firewall

PC-B (visualizador):
    streamlit run visualizador.py
    → en el sidebar cambia IP a 192.168.1.50
    → presiona "Conectar al servidor"
```

---

## 7. Estructura del repositorio

```
.
├── servidor.cpp              # Proceso servidor (C++) — genera placas
├── libreria_lockers.cpp      # Fuente de la DLL (C++) — cliente socket + lógica
├── visualizador.py           # Dashboard Streamlit (Python + ctypes)
├── compilar.bat              # Script de compilación (Windows)
├── docs/
│   ├── uml_componentes.puml
│   ├── uml_secuencia.puml
│   └── uml_clases.puml
├── README.md
└── .gitignore
```
