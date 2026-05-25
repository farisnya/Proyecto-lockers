/* lockers.i — Interfaz SWIG para SmartLocker System
 *
 * Genera los bindings Python de la clase SistemaLockers.
 *
 * Uso:
 *   swig -c++ -python lockers.i
 *   g++ -shared -o _lockers.pyd lockers_wrap.cxx libreria_lockers.cpp \
 *       -I"%PYTHON_INCLUDE%" -L"%PYTHON_LIBS%" -lpython3XX -lws2_32 -static
 */

%module lockers

%{
#include "libreria_lockers.h"
%}

%include <std_string.i>
%include <std_vector.i>

%template(ListaLockers) std::vector<EstadoLocker>;

%include "libreria_lockers.h"
