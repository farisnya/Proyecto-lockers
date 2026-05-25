/*
 * cliente_locker.cpp
 * ============================================================
 * PC Cliente del sistema de lockers.
 *
 * - Se conecta al servidor.exe por TCP.
 * - Permite OCUPAR y LIBERAR lockers desde este PC.
 * - Recibe notificaciones en tiempo real cuando CUALQUIER
 *   otro PC (o el servidor) cambia el estado de un locker.
 * - Muestra el panel de lockers actualizado en consola.
 *
 * Compilar Windows (MinGW / MSYS2):
 *   g++ -o cliente_locker.exe cliente_locker.cpp -lws2_32 -std=c++17
 *
 * Compilar Linux:
 *   g++ -o cliente_locker cliente_locker.cpp -std=c++17 -lpthread
 *
 * Uso:
 *   cliente_locker.exe [IP_servidor] [puerto]
 *   cliente_locker.exe 192.168.1.10 8888
 * ============================================================
 */

#ifdef _WIN32
  #include <winsock2.h>
  #include <ws2tcpip.h>
  #pragma comment(lib, "ws2_32.lib")
  #define CLEAR_SCREEN "cls"
  typedef SOCKET SocketHandle;
  #define INVALID_SOCK  INVALID_SOCKET
  #define CLOSE_SOCK(s) closesocket(s)
#else
  #include <sys/socket.h>
  #include <arpa/inet.h>
  #include <unistd.h>
  #define CLEAR_SCREEN "clear"
  typedef int SocketHandle;
  #define INVALID_SOCK  -1
  #define CLOSE_SOCK(s) close(s)
#endif

#include <iostream>
#include <string>
#include <map>
#include <mutex>
#include <thread>
#include <atomic>
#include <chrono>
#include <sstream>
#include <vector>
#include <algorithm>
#include <ctime>

using namespace std;

// ── Estado de lockers (vista local) ────────────────────────
static mutex              g_mtx;
static map<int,string>    g_lockers;    // locker# -> codigo (vacío = libre)
static atomic<bool>       g_corriendo{true};
static atomic<bool>       g_conectado{false};
static SocketHandle       g_sock = INVALID_SOCK;
static vector<string>     g_log;        // historial de eventos

// ── Helpers ─────────────────────────────────────────────────
string horaActual() {
    time_t ahora = time(0);
    char buf[64];
#ifdef _WIN32
    ctime_s(buf, sizeof(buf), &ahora);
#else
    ctime_r(&ahora, buf);
#endif
    string h(buf);
    while (!h.empty() && (h.back()=='\n'||h.back()=='\r')) h.pop_back();
    // Solo HH:MM:SS
    if (h.size() >= 19) return h.substr(11, 8);
    return h;
}

string extraer(const string& msg, const string& campo, const string& siguiente) {
    size_t ini = msg.find(campo);
    if (ini == string::npos) return "";
    ini += campo.size();
    size_t fin = siguiente.empty() ? string::npos : msg.find(siguiente, ini);
    string val = msg.substr(ini, fin == string::npos ? fin : fin - ini);
    while (!val.empty() && (val.back()=='\n'||val.back()=='\r'||val.back()==' ')) val.pop_back();
    return val;
}

void agregar_log(const string& linea) {
    g_log.insert(g_log.begin(), "[" + horaActual() + "] " + linea);
    if ((int)g_log.size() > 12) g_log.resize(12);
}

// ── Dibujar panel en consola ─────────────────────────────────
void dibujar_panel() {
    system(CLEAR_SCREEN);
    cout << "╔══════════════════════════════════════════════╗" << endl;
    cout << "║       SISTEMA DE LOCKERS  —  PC CLIENTE      ║" << endl;
    cout << "╚══════════════════════════════════════════════╝" << endl;

    string estado_conn = g_conectado.load()
        ? "  ● CONECTADO AL SERVIDOR"
        : "  ○ DESCONECTADO";
    cout << estado_conn << endl;
    cout << "────────────────────────────────────────────────" << endl;

    // Grid de lockers 2 filas x 5 columnas
    lock_guard<mutex> lk(g_mtx);
    for (int fila = 0; fila < 2; fila++) {
        // Fila de números
        for (int col = 0; col < 5; col++) {
            int n = fila * 5 + col + 1;
            cout << "┌───────┐  ";
        }
        cout << endl;
        for (int col = 0; col < 5; col++) {
            int n = fila * 5 + col + 1;
            bool ocup = !g_lockers[n].empty();
            string icono = ocup ? " OCUP  " : " LIBRE ";
            cout << "│" << icono << "│  ";
        }
        cout << endl;
        for (int col = 0; col < 5; col++) {
            int n = fila * 5 + col + 1;
            char buf[10];
            snprintf(buf, sizeof(buf), "  #%02d  ", n);
            cout << "│" << buf << "│  ";
        }
        cout << endl;
        for (int col = 0; col < 5; col++) {
            int n = fila * 5 + col + 1;
            bool ocup = !g_lockers[n].empty();
            string cod = ocup ? g_lockers[n] : "      ";
            if (cod.size() > 6) cod = cod.substr(0, 6);
            while ((int)cod.size() < 6) cod += " ";
            cout << "│ " << cod << " │  ";
        }
        cout << endl;
        for (int col = 0; col < 5; col++) {
            cout << "└───────┘  ";
        }
        cout << endl << endl;
    }

    cout << "────────────────────────────────────────────────" << endl;
    cout << "  ACTIVIDAD RECIENTE:" << endl;
    for (auto& l : g_log) cout << "  " << l << endl;
    cout << "────────────────────────────────────────────────" << endl;
    cout << endl;
    cout << "  COMANDOS:" << endl;
    cout << "  o <N> <CODIGO>   → Ocupar locker N con código" << endl;
    cout << "  l <N> <CODIGO>   → Liberar locker N con código" << endl;
    cout << "  q                → Salir" << endl;
    cout << "> " << flush;
}

// ── Procesar mensaje recibido del servidor ──────────────────
void procesar_mensaje(const string& msg) {
    if (msg.find("CMD:") == 0) return;         // ignorar ecos de comandos
    if (msg.find("ERROR:") == 0) {
        agregar_log("Error servidor: " + msg);
        return;
    }

    string codigo = extraer(msg, "Codigo:", "|Hora:");
    string locker_s = extraer(msg, "|Locker:", "");
    if (codigo.empty() || locker_s.empty()) return;

    int locker = 0;
    try { locker = stoi(locker_s); } catch (...) { return; }
    if (locker < 1 || locker > 10) return;

    string accion;
    {
        lock_guard<mutex> lk(g_mtx);
        auto it = g_lockers.find(locker);
        bool ya_ocupado = (it != g_lockers.end() && !it->second.empty());

        if (ya_ocupado && g_lockers[locker] == codigo) {
            g_lockers[locker] = "";
            accion = "LIBERADO";
        } else {
            g_lockers[locker] = codigo;
            accion = "OCUPADO ";
        }
    }

    agregar_log(accion + " → Locker #" + locker_s + "  [" + codigo + "]");
    dibujar_panel();
}

// ── Hilo de lectura del servidor ─────────────────────────────
void hilo_recepcion(SocketHandle sock) {
    char tmp[4096];
    string buffer;

    while (g_corriendo.load()) {
        int n = recv(sock, tmp, sizeof(tmp)-1, 0);
        if (n <= 0) {
            g_conectado = false;
            agregar_log("Conexión con el servidor perdida.");
            dibujar_panel();
            break;
        }
        tmp[n] = '\0';
        buffer += tmp;

        // Extraer mensajes completos (contienen Codigo: y Locker:)
        while (true) {
            size_t ini = buffer.find("Codigo:");
            if (ini == string::npos) {
                // Puede ser un ERROR: suelto
                size_t err = buffer.find("ERROR:");
                if (err != string::npos) {
                    size_t nl = buffer.find('\n', err);
                    string emsg = buffer.substr(err, nl == string::npos ? string::npos : nl - err);
                    agregar_log("Servidor: " + emsg);
                    buffer = nl == string::npos ? "" : buffer.substr(nl+1);
                    dibujar_panel();
                    continue;
                }
                buffer.clear();
                break;
            }

            if (buffer.find("|Hora:",   ini) == string::npos) break;
            if (buffer.find("|Locker:", ini) == string::npos) break;

            size_t sig = buffer.find("Codigo:", ini + 1);
            string msg;
            if (sig == string::npos) { msg = buffer.substr(ini); buffer.clear(); }
            else                     { msg = buffer.substr(ini, sig-ini); buffer = buffer.substr(sig); }

            while (!msg.empty() && (msg.back()=='\n'||msg.back()=='\r'||msg.back()==' '))
                msg.pop_back();

            if (!msg.empty()) procesar_mensaje(msg);
        }
    }
}

// ── Enviar comando al servidor ───────────────────────────────
bool enviar_comando(const string& accion, int locker, const string& codigo) {
    if (!g_conectado.load()) {
        cout << "  ✗ No estás conectado al servidor." << endl;
        return false;
    }
    string cmd = "CMD:" + accion +
                 "|Locker:" + to_string(locker) +
                 "|Codigo:" + codigo + "\n";
    int r = send(g_sock, cmd.c_str(), (int)cmd.size(), 0);
    return r > 0;
}

// ── main ─────────────────────────────────────────────────────
int main(int argc, char* argv[]) {
    string ip_srv  = (argc >= 2) ? argv[1] : "127.0.0.1";
    int    puerto  = (argc >= 3) ? atoi(argv[2]) : 8888;

    // Inicializar lockers a vacío
    for (int i = 1; i <= 10; i++) g_lockers[i] = "";

#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2,2), &wsa);
#endif

    // ── Conectar al servidor ────────────────────────────────
    cout << "Conectando a " << ip_srv << ":" << puerto << " ..." << endl;

    SocketHandle sock = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons((u_short)puerto);
    inet_pton(AF_INET, ip_srv.c_str(), &addr.sin_addr);

    if (connect(sock, (sockaddr*)&addr, sizeof(addr)) != 0) {
        cerr << "No se pudo conectar al servidor en "
             << ip_srv << ":" << puerto << endl;
        return 1;
    }

    g_sock      = sock;
    g_conectado = true;
    agregar_log("Conectado al servidor " + ip_srv + ":" + to_string(puerto));

    // Lanzar hilo de recepción
    thread(hilo_recepcion, sock).detach();

    dibujar_panel();

    // ── Loop de entrada del usuario ─────────────────────────
    string linea;
    while (g_corriendo.load() && getline(cin, linea)) {
        // Limpiar
        while (!linea.empty() && (linea.back()=='\r'||linea.back()=='\n'||linea.back()==' '))
            linea.pop_back();
        if (linea.empty()) { dibujar_panel(); continue; }

        char cmd   = linea[0];
        istringstream ss(linea.substr(1));

        if (cmd == 'q' || cmd == 'Q') {
            g_corriendo = false;
            break;
        }
        else if (cmd == 'o' || cmd == 'O') {
            int n; string cod;
            if (ss >> n >> cod) {
                if (n < 1 || n > 10) {
                    agregar_log("Número de locker inválido (1-10)");
                } else if (cod.empty()) {
                    agregar_log("Debes indicar un código");
                } else {
                    transform(cod.begin(), cod.end(), cod.begin(), ::toupper);
                    if (enviar_comando("OCUPAR", n, cod)) {
                        agregar_log("CMD enviado → OCUPAR Locker #" + to_string(n) + " [" + cod + "]");
                    }
                }
            } else {
                agregar_log("Uso: o <N> <CODIGO>  (ej: o 3 ABC123)");
            }
        }
        else if (cmd == 'l' || cmd == 'L') {
            int n; string cod;
            if (ss >> n >> cod) {
                if (n < 1 || n > 10) {
                    agregar_log("Número de locker inválido (1-10)");
                } else {
                    transform(cod.begin(), cod.end(), cod.begin(), ::toupper);
                    if (enviar_comando("LIBERAR", n, cod)) {
                        agregar_log("CMD enviado → LIBERAR Locker #" + to_string(n) + " [" + cod + "]");
                    }
                }
            } else {
                agregar_log("Uso: l <N> <CODIGO>  (ej: l 3 ABC123)");
            }
        }
        else {
            agregar_log("Comando desconocido. Usa: o / l / q");
        }

        dibujar_panel();
    }

    g_corriendo = false;
    CLOSE_SOCK(sock);
#ifdef _WIN32
    WSACleanup();
#endif
    cout << "Saliendo..." << endl;
    return 0;
}
