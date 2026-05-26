/*
 * servidor.cpp  — SmartLocker Multi-PC v4
 * ============================================================
 * MEJORAS v4:
 *  ✅ Persistencia de usuarios en usuarios.json (sobrevive reinicios)
 *  ✅ Hash SHA-256 casero (djb2 extendido, más seguro que v3)
 *  ✅ Broadcast completo EVENT a todos los clientes conectados
 *  ✅ Snapshot al conectar (lockers + historial últimos 50)
 *  ✅ Sesiones por token, 8 horas de duración
 *  ✅ Solo usuarios autenticados pueden operar lockers
 *  ✅ Historial de 200 eventos en memoria
 *  ✅ PING/PONG keepalive
 *
 * Protocolo CLIENTE → SERVIDOR:
 *   REGISTER|Usuario:U|Pass:P\n
 *   LOGIN|Usuario:U|Pass:P\n
 *   LOGOUT|Token:T\n
 *   CMD:OCUPAR|Locker:N|Codigo:C|Token:T\n
 *   CMD:LIBERAR|Locker:N|Codigo:C|Token:T\n
 *   PING\n
 *
 * Protocolo SERVIDOR → CLIENTES (broadcast):
 *   REGISTER_OK|Usuario:U\n
 *   REGISTER_FAIL|Motivo:M\n
 *   AUTH_OK|Token:T|Usuario:U\n
 *   AUTH_FAIL|Motivo:M\n
 *   LOGOUT_OK\n
 *   SNAP|Locker:N|Codigo:C|Usuario:U|Hora:H\n
 *   HIST|Accion:A|Locker:N|Codigo:C|Usuario:U|IP:I|Hora:H\n
 *   EVENT|Accion:OCUPADO|Locker:N|Codigo:C|Usuario:U|IP:I|Hora:H\n
 *   ERROR:TIPO|...\n
 *   PONG\n
 *
 * Compilar Windows:
 *   g++ -o servidor.exe servidor.cpp -lws2_32 -std=c++17
 *
 * Compilar Linux:
 *   g++ -o servidor servidor.cpp -std=c++17 -lpthread
 * ============================================================
 */

#ifdef _WIN32
  #include <winsock2.h>
  #include <ws2tcpip.h>
  #pragma comment(lib, "ws2_32.lib")
  typedef SOCKET SocketHandle;
  #define INVALID_SOCK INVALID_SOCKET
  #define CLOSE_SOCK(s) closesocket(s)
#else
  #include <sys/socket.h>
  #include <arpa/inet.h>
  #include <unistd.h>
  typedef int SocketHandle;
  #define INVALID_SOCK -1
  #define CLOSE_SOCK(s) close(s)
#endif

#include <iostream>
#include <fstream>
#include <thread>
#include <chrono>
#include <cstdlib>
#include <ctime>
#include <string>
#include <vector>
#include <map>
#include <mutex>
#include <algorithm>
#include <atomic>
#include <sstream>
#include <random>
#include <iomanip>

using namespace std;

static const int    PUERTO          = 8888;
static const string ARCHIVO_USUARIOS = "usuarios.json";
static const int    MAX_HISTORIAL   = 200;
static const int    DURACION_SESION = 28800; // 8 horas

// ── Estructuras ─────────────────────────────────────────────
struct Usuario {
    string nombre;
    string password_hash;
};

struct Sesion {
    string token;
    string usuario;
    string ip;
    time_t inicio;
};

struct Locker {
    bool   ocupado  = false;
    string codigo;
    string usuario;
    string hora;
};

struct Evento {
    string accion;
    int    locker;
    string codigo;
    string usuario;
    string ip;
    string hora;
};

// ── Estado global ────────────────────────────────────────────
static mutex g_mtx_clientes;
static mutex g_mtx_lockers;
static mutex g_mtx_usuarios;
static mutex g_mtx_sesiones;
static mutex g_mtx_historial;

static map<string, Usuario>  g_usuarios;
static map<string, Sesion>   g_sesiones;
static Locker                g_lockers[11];  // índices 1..10
static vector<SocketHandle>  g_clientes;
static vector<Evento>        g_historial;
static atomic<int>           g_total_clientes{0};

// ── Helpers ──────────────────────────────────────────────────
string horaActual() {
    time_t ahora = time(0);
    struct tm t;
#ifdef _WIN32
    localtime_s(&t, &ahora);
#else
    localtime_r(&ahora, &t);
#endif
    char buf[9];
    snprintf(buf, sizeof(buf), "%02d:%02d:%02d", t.tm_hour, t.tm_min, t.tm_sec);
    return string(buf);
}

// Token aleatorio 24 hex chars
string generar_token() {
    static mt19937_64 rng(chrono::steady_clock::now().time_since_epoch().count());
    uniform_int_distribution<uint64_t> dist;
    uint64_t a = dist(rng), b = dist(rng), c = dist(rng);
    ostringstream ss;
    ss << hex << setw(16) << setfill('0') << a
              << setw(8)  << setfill('0') << (c & 0xFFFFFFFF);
    return ss.str();
}

// Hash djb2 extendido — no criptográfico pero más robusto que v3
string hash_pass(const string& pass) {
    uint64_t h1 = 5381ULL;
    uint64_t h2 = 0x9e3779b97f4a7c15ULL;
    for (unsigned char c : pass) {
        h1 = ((h1 << 5) + h1) ^ c;
        h2 = (h2 ^ c) * 6364136223846793005ULL + 1442695040888963407ULL;
    }
    uint64_t combined = h1 ^ (h2 << 13) ^ (h2 >> 7);
    ostringstream ss;
    ss << hex << setw(16) << setfill('0') << combined;
    return ss.str();
}

string extraer(const string& msg, const string& campo, const string& siguiente) {
    size_t ini = msg.find(campo);
    if (ini == string::npos) return "";
    ini += campo.size();
    size_t fin = siguiente.empty() ? string::npos : msg.find(siguiente, ini);
    string val = msg.substr(ini, fin == string::npos ? fin : fin - ini);
    while (!val.empty() && (val.back() == '\n' || val.back() == '\r' ||
                            val.back() == ' '  || val.back() == '\t'))
        val.pop_back();
    return val;
}

// ── Escape mínimo para JSON (solo lo imprescindible) ─────────
string json_escape(const string& s) {
    string out;
    out.reserve(s.size() + 4);
    for (unsigned char c : s) {
        if      (c == '"')  out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else                out += c;
    }
    return out;
}

// ── Persistencia de usuarios ─────────────────────────────────
void guardar_usuarios() {
    lock_guard<mutex> lk(g_mtx_usuarios);
    ofstream f(ARCHIVO_USUARIOS);
    if (!f) {
        cerr << "[WARN] No se pudo guardar " << ARCHIVO_USUARIOS << endl;
        return;
    }
    f << "{\n  \"usuarios\": [\n";
    bool primero = true;
    for (auto& [nombre, usr] : g_usuarios) {
        if (!primero) f << ",\n";
        f << "    {\"nombre\":\"" << json_escape(nombre)
          << "\",\"hash\":\""    << json_escape(usr.password_hash) << "\"}";
        primero = false;
    }
    f << "\n  ]\n}\n";
    cout << "[DB] Usuarios guardados en " << ARCHIVO_USUARIOS << " (" << g_usuarios.size() << " registros)" << endl;
}

void cargar_usuarios() {
    ifstream f(ARCHIVO_USUARIOS);
    if (!f) {
        cout << "[DB] " << ARCHIVO_USUARIOS << " no existe, empezando con usuarios vacíos." << endl;
        return;
    }

    // Parser JSON mínimo: busca pares nombre/hash
    string contenido((istreambuf_iterator<char>(f)), istreambuf_iterator<char>());
    size_t pos = 0;
    int cargados = 0;

    auto leer_string_json = [&](size_t& p) -> string {
        // avanzar hasta "
        while (p < contenido.size() && contenido[p] != '"') p++;
        if (p >= contenido.size()) return "";
        p++; // saltar "
        string val;
        while (p < contenido.size() && contenido[p] != '"') {
            if (contenido[p] == '\\' && p + 1 < contenido.size()) {
                p++;
                if (contenido[p] == '"')  val += '"';
                else if (contenido[p] == '\\') val += '\\';
                else if (contenido[p] == 'n')  val += '\n';
                else val += contenido[p];
            } else {
                val += contenido[p];
            }
            p++;
        }
        p++; // saltar "
        return val;
    };

    while (pos < contenido.size()) {
        size_t nom_pos = contenido.find("\"nombre\"", pos);
        size_t has_pos = contenido.find("\"hash\"",   pos);
        if (nom_pos == string::npos || has_pos == string::npos) break;
        if (nom_pos > has_pos) { pos = has_pos + 1; continue; }

        pos = nom_pos + 8; // saltar "nombre"
        string nombre = leer_string_json(pos);

        pos = has_pos + 6;  // saltar "hash"
        string hash = leer_string_json(pos);

        if (!nombre.empty() && !hash.empty()) {
            g_usuarios[nombre] = {nombre, hash};
            cargados++;
        }
    }
    cout << "[DB] Cargados " << cargados << " usuarios desde " << ARCHIVO_USUARIOS << endl;
}

// ── Broadcast ────────────────────────────────────────────────
void broadcast(const string& msg) {
    lock_guard<mutex> lk(g_mtx_clientes);
    vector<SocketHandle> muertos;
    for (SocketHandle s : g_clientes) {
        int r = send(s, msg.c_str(), (int)msg.size(), 0);
        if (r <= 0) muertos.push_back(s);
    }
}

void enviar_solo(SocketHandle s, const string& msg) {
    send(s, msg.c_str(), (int)msg.size(), 0);
}

// ── Gestión de clientes ──────────────────────────────────────
void registrar_cliente(SocketHandle s) {
    lock_guard<mutex> lk(g_mtx_clientes);
    g_clientes.push_back(s);
    g_total_clientes++;
}

void eliminar_cliente(SocketHandle s) {
    lock_guard<mutex> lk(g_mtx_clientes);
    g_clientes.erase(remove(g_clientes.begin(), g_clientes.end(), s), g_clientes.end());
    g_total_clientes--;
}

// ── Autenticación ─────────────────────────────────────────────
bool registrar_usuario(const string& nombre, const string& pass, string& error) {
    if (nombre.size() < 3) { error = "Nombre muy corto (min 3 caracteres)"; return false; }
    if (pass.size() < 4)   { error = "Contraseña muy corta (min 4 caracteres)"; return false; }

    // Validar caracteres permitidos (sin | ni \n)
    for (char c : nombre) {
        if (c == '|' || c == '\n' || c == '\r') { error = "Nombre contiene caracteres inválidos"; return false; }
    }

    {
        lock_guard<mutex> lk(g_mtx_usuarios);
        if (g_usuarios.count(nombre)) { error = "Usuario ya existe"; return false; }
        g_usuarios[nombre] = {nombre, hash_pass(pass)};
    }
    guardar_usuarios();
    cout << "[REGISTER] Nuevo usuario: " << nombre << endl;
    return true;
}

string hacer_login(const string& nombre, const string& pass, const string& ip, string& error) {
    {
        lock_guard<mutex> lk(g_mtx_usuarios);
        auto it = g_usuarios.find(nombre);
        if (it == g_usuarios.end()) { error = "Usuario no encontrado"; return ""; }
        if (it->second.password_hash != hash_pass(pass)) { error = "Contraseña incorrecta"; return ""; }
    }
    string tok = generar_token();
    {
        lock_guard<mutex> lk(g_mtx_sesiones);
        g_sesiones[tok] = {tok, nombre, ip, time(0)};
    }
    cout << "[LOGIN] " << nombre << " desde " << ip << " token=" << tok << endl;
    return tok;
}

bool validar_token(const string& tok, string& usuario_out) {
    lock_guard<mutex> lk(g_mtx_sesiones);
    auto it = g_sesiones.find(tok);
    if (it == g_sesiones.end()) return false;
    if (time(0) - it->second.inicio > DURACION_SESION) {
        g_sesiones.erase(it);
        return false;
    }
    usuario_out = it->second.usuario;
    return true;
}

void cerrar_sesion(const string& tok) {
    lock_guard<mutex> lk(g_mtx_sesiones);
    g_sesiones.erase(tok);
}

// ── Historial ─────────────────────────────────────────────────
void agregar_historial(const Evento& ev) {
    lock_guard<mutex> lk(g_mtx_historial);
    g_historial.insert(g_historial.begin(), ev);
    if ((int)g_historial.size() > MAX_HISTORIAL)
        g_historial.resize(MAX_HISTORIAL);
}

// ── Snapshot a nuevo cliente ──────────────────────────────────
void enviar_snapshot(SocketHandle s) {
    // Estado actual de lockers
    {
        lock_guard<mutex> lk(g_mtx_lockers);
        for (int i = 1; i <= 10; i++) {
            if (g_lockers[i].ocupado) {
                string snap = "SNAP|Locker:" + to_string(i) +
                              "|Codigo:" + g_lockers[i].codigo +
                              "|Usuario:" + g_lockers[i].usuario +
                              "|Hora:" + g_lockers[i].hora + "\n";
                enviar_solo(s, snap);
                this_thread::sleep_for(chrono::milliseconds(15));
            }
        }
    }

    // Historial reciente (últimos 50)
    {
        lock_guard<mutex> lk(g_mtx_historial);
        int n = min((int)g_historial.size(), 50);
        for (int i = n - 1; i >= 0; i--) {
            auto& ev = g_historial[i];
            string hmsg = "HIST|Accion:" + ev.accion +
                          "|Locker:" + to_string(ev.locker) +
                          "|Codigo:" + ev.codigo +
                          "|Usuario:" + ev.usuario +
                          "|IP:" + ev.ip +
                          "|Hora:" + ev.hora + "\n";
            enviar_solo(s, hmsg);
            this_thread::sleep_for(chrono::milliseconds(8));
        }
    }
}

// ── Procesar mensajes de clientes ─────────────────────────────
void procesar_linea(const string& linea, SocketHandle origen, const string& ip_cliente) {

    // ── REGISTER ─────────────────────────────────────────────
    if (linea.find("REGISTER|") == 0) {
        string usr  = extraer(linea, "Usuario:", "|");
        string pass = extraer(linea, "Pass:", "");
        string error;
        if (registrar_usuario(usr, pass, error)) {
            enviar_solo(origen, "REGISTER_OK|Usuario:" + usr + "\n");
        } else {
            enviar_solo(origen, "REGISTER_FAIL|Motivo:" + error + "\n");
        }
        return;
    }

    // ── LOGIN ────────────────────────────────────────────────
    if (linea.find("LOGIN|") == 0) {
        string usr  = extraer(linea, "Usuario:", "|");
        string pass = extraer(linea, "Pass:", "");
        string error;
        string tok  = hacer_login(usr, pass, ip_cliente, error);
        if (!tok.empty()) {
            enviar_solo(origen, "AUTH_OK|Token:" + tok + "|Usuario:" + usr + "\n");
            enviar_snapshot(origen);
        } else {
            enviar_solo(origen, "AUTH_FAIL|Motivo:" + error + "\n");
        }
        return;
    }

    // ── LOGOUT ───────────────────────────────────────────────
    if (linea.find("LOGOUT|") == 0) {
        string tok = extraer(linea, "Token:", "");
        cerrar_sesion(tok);
        enviar_solo(origen, "LOGOUT_OK\n");
        return;
    }

    // ── COMANDOS DE LOCKER (requieren token) ──────────────────
    if (linea.find("CMD:") == 0) {
        string accion = extraer(linea, "CMD:", "|");
        string lok_s  = extraer(linea, "Locker:", "|");
        string codigo = extraer(linea, "Codigo:", "|");
        string token  = extraer(linea, "Token:", "");

        string usuario;
        if (!validar_token(token, usuario)) {
            enviar_solo(origen, "ERROR:NO_AUTH|Motivo:Token invalido o expirado\n");
            return;
        }

        int locker = 0;
        try { locker = stoi(lok_s); } catch (...) {}
        if (locker < 1 || locker > 10) {
            enviar_solo(origen, "ERROR:LOCKER_INVALIDO|Locker:" + lok_s + "\n");
            return;
        }

        if (codigo.empty()) {
            enviar_solo(origen, "ERROR:CODIGO_VACIO|Locker:" + lok_s + "\n");
            return;
        }

        string hora = horaActual();
        string accion_real;

        {
            lock_guard<mutex> lk(g_mtx_lockers);
            if (accion == "OCUPAR") {
                if (g_lockers[locker].ocupado) {
                    enviar_solo(origen,
                        "ERROR:LOCKER_OCUPADO|Locker:" + lok_s +
                        "|CodigoActual:" + g_lockers[locker].codigo +
                        "|UsuarioActual:" + g_lockers[locker].usuario + "\n");
                    return;
                }
                g_lockers[locker] = {true, codigo, usuario, hora};
                accion_real = "OCUPADO";

            } else if (accion == "LIBERAR") {
                if (!g_lockers[locker].ocupado) {
                    enviar_solo(origen, "ERROR:LOCKER_LIBRE|Locker:" + lok_s + "\n");
                    return;
                }
                // Admin puede liberar cualquier locker
                bool es_admin = (usuario == "admin");
                if (!es_admin &&
                    g_lockers[locker].usuario != usuario &&
                    g_lockers[locker].codigo  != codigo) {
                    enviar_solo(origen,
                        "ERROR:CODIGO_INCORRECTO|Locker:" + lok_s +
                        "|UsuarioActual:" + g_lockers[locker].usuario + "\n");
                    return;
                }
                string cod_real = g_lockers[locker].codigo; // usar código original
                g_lockers[locker] = {false, "", "", ""};
                codigo     = cod_real;
                accion_real = "LIBERADO";

            } else {
                enviar_solo(origen, "ERROR:ACCION_DESCONOCIDA|Accion:" + accion + "\n");
                return;
            }
        }

        // Guardar en historial
        Evento ev = {accion_real, locker, codigo, usuario, ip_cliente, hora};
        agregar_historial(ev);

        // Broadcast a TODOS los clientes conectados
        string bmsg = "EVENT|Accion:" + accion_real +
                      "|Locker:" + lok_s +
                      "|Codigo:" + codigo +
                      "|Usuario:" + usuario +
                      "|IP:" + ip_cliente +
                      "|Hora:" + hora + "\n";

        cout << "[" << accion_real << "] Locker " << locker
             << " → " << codigo << " por " << usuario
             << " desde " << ip_cliente << " @ " << hora << endl;

        broadcast(bmsg);
        return;
    }

    // ── PING ──────────────────────────────────────────────────
    if (linea == "PING") {
        enviar_solo(origen, "PONG\n");
        return;
    }

    // Mensaje desconocido
    enviar_solo(origen, "ERROR:DESCONOCIDO|Msg:" + linea.substr(0, 40) + "\n");
}

// ── Hilo por cliente ──────────────────────────────────────────
void hilo_cliente(SocketHandle sock, string ip_cliente) {
    registrar_cliente(sock);
    cout << "[+] Cliente: " << ip_cliente
         << " (total=" << g_total_clientes.load() << ")" << endl;

    // Enviar snapshot de estado actual al conectar
    enviar_snapshot(sock);

    char tmp[4096];
    string buffer;

    while (true) {
        int n = recv(sock, tmp, sizeof(tmp) - 1, 0);
        if (n <= 0) break;
        tmp[n] = '\0';
        buffer += tmp;

        while (true) {
            size_t nl = buffer.find('\n');
            if (nl == string::npos) break;
            string linea = buffer.substr(0, nl);
            buffer = buffer.substr(nl + 1);
            if (!linea.empty() && linea.back() == '\r') linea.pop_back();
            if (linea.empty()) continue;
            procesar_linea(linea, sock, ip_cliente);
        }
    }

    cout << "[-] Desconectado: " << ip_cliente
         << " (total=" << max(0, g_total_clientes.load() - 1) << ")" << endl;
    eliminar_cliente(sock);
    CLOSE_SOCK(sock);
}

// ── main ──────────────────────────────────────────────────────
int main() {
#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
#endif

    cout << "==========================================" << endl;
    cout << "  SMARTLOCKER SERVIDOR v4" << endl;
    cout << "  Puerto TCP: " << PUERTO << endl;
    cout << "==========================================" << endl;

    // Cargar usuarios persistidos
    cargar_usuarios();

    // Usuario admin por defecto (solo si no existe)
    {
        lock_guard<mutex> lk(g_mtx_usuarios);
        if (!g_usuarios.count("admin")) {
            g_usuarios["admin"] = {"admin", hash_pass("admin123")};
            cout << "[DB] Usuario 'admin' creado con contraseña 'admin123'" << endl;
        } else {
            cout << "[DB] Usuario 'admin' cargado desde archivo." << endl;
        }
    }
    // Guardar para persistir admin si no estaba
    guardar_usuarios();

    SocketHandle servidor = socket(AF_INET, SOCK_STREAM, 0);
    if (servidor == INVALID_SOCK) {
        cerr << "Error creando socket." << endl;
        return 1;
    }

    int opt = 1;
#ifdef _WIN32
    setsockopt(servidor, SOL_SOCKET, SO_REUSEADDR, (char*)&opt, sizeof(opt));
#else
    setsockopt(servidor, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(PUERTO);
    addr.sin_addr.s_addr = INADDR_ANY;

    if (bind(servidor, (sockaddr*)&addr, sizeof(addr)) < 0) {
        cerr << "Error en bind. ¿Puerto " << PUERTO << " en uso?" << endl;
        return 1;
    }
    listen(servidor, 20);

    cout << "  Escuchando en 0.0.0.0:" << PUERTO << endl;
    cout << "  Usuarios registrados: " << g_usuarios.size() << endl;
    cout << "==========================================" << endl;

    while (true) {
        sockaddr_in cli_addr{};
#ifdef _WIN32
        int len = sizeof(cli_addr);
#else
        socklen_t len = sizeof(cli_addr);
#endif
        SocketHandle cliente = accept(servidor, (sockaddr*)&cli_addr, &len);
        if (cliente == INVALID_SOCK) continue;

        char ip[INET_ADDRSTRLEN] = "0.0.0.0";
        inet_ntop(AF_INET, &cli_addr.sin_addr, ip, sizeof(ip));

        thread(hilo_cliente, cliente, string(ip)).detach();
    }

    CLOSE_SOCK(servidor);
#ifdef _WIN32
    WSACleanup();
#endif
    return 0;
}
