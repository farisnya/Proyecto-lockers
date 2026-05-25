/**
 * libreria_lockers.h — SmartLocker System
 * =========================================
 * Cabecera de la clase SistemaLockers (cliente del servidor).
 * 
 * Flujo:
 *   conectar() → enviarCodigo(codigo) → leerRespuesta()
 *
 * Exportada a Python vía SWIG (lockers.i).
 */

#pragma once

#ifdef _WIN32
  #include <winsock2.h>
  #include <ws2tcpip.h>
  typedef SOCKET socket_t;
  #define INVALID_SOCK INVALID_SOCKET
#else
  #include <sys/socket.h>
  #include <netinet/in.h>
  #include <arpa/inet.h>
  #include <unistd.h>
  typedef int socket_t;
  #define INVALID_SOCK (-1)
#endif

#include <string>
#include <map>
#include <vector>

// ── Estructura de estado por locker ──────────────────────────────

struct EstadoLocker {
    int         numero;
    bool        ocupado;
    std::string codigo;
    std::string hora;

    EstadoLocker() : numero(0), ocupado(false) {}
    EstadoLocker(int n, bool o, const std::string& c, const std::string& h)
        : numero(n), ocupado(o), codigo(c), hora(h) {}
};

// ── Clase cliente ─────────────────────────────────────────────────

class SistemaLockers {
public:
    SistemaLockers();
    ~SistemaLockers();

    /** Conecta al servidor. Retorna 0 si OK, negativo si error. */
    int conectar(const std::string& ip, int puerto);

    /**
     * Envía un código al servidor y espera la respuesta.
     * Retorna: "OCUPADO:Locker:N|..." / "LIBERADO:Locker:N|..." / "SIN_LOCKERS|..."
     */
    std::string enviarCodigo(const std::string& codigo);

    /** Actualiza el estado interno con la respuesta del servidor. */
    std::string procesarRespuesta(const std::string& respuesta);

    /** Cantidad de lockers ocupados según el estado local. */
    int cantidadOcupados() const;

    /** true si el socket está conectado. */
    bool estaConectado() const;

    /** Cierra el socket. */
    void desconectar();

    /** Estado completo en JSON. */
    std::string obtenerEstadoJSON() const;

    /** Vector con el estado de cada locker. */
    std::vector<EstadoLocker> obtenerEstados() const;

private:
    static const int NUM_LOCKERS = 10;

    socket_t    sock_;
    bool        iniciado_;

    std::map<std::string, int>  codigoALocker_;
    std::map<int, std::string>  lockerACodigo_;
    std::map<int, std::string>  lockerAHora_;
};

// ── Funciones C (compatibilidad ctypes) ──────────────────────────

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _WIN32
  #define LOCKER_API __declspec(dllexport)
#else
  #define LOCKER_API
#endif

LOCKER_API int         conectar_c(const char* ip, int puerto);
LOCKER_API const char* enviar_codigo_c(const char* codigo);
LOCKER_API int         cantidad_ocupados_c(void);
LOCKER_API void        desconectar_c(void);

#ifdef __cplusplus
}
#endif
