# SmartLocker System

Sistema inteligente de lockers desarrollado como proyecto académico utilizando comunicación cliente-servidor mediante sockets en C++, visualización en Python y una interfaz web para monitoreo en tiempo real.

---

# Descripción del Proyecto

SmartLocker System es una solución tecnológica que simula la gestión automatizada de lockers inteligentes para recepción y entrega de paquetes.

El sistema funciona mediante la generación de códigos únicos de paquetes que son enviados desde un cliente hacia un servidor utilizando sockets en C++.

El servidor procesa la información y determina:

- Asignación de lockers libres
- Liberación de lockers ocupados
- Registro de hora y estado
- Monitoreo en tiempo real

El visualizador permite observar el estado de cada locker de forma dinámica.

---

# Objetivos

## Objetivo General
Desarrollar un sistema inteligente de lockers empleando comunicación cliente-servidor y visualización en tiempo real.

## Objetivos Específicos

- Implementar sockets en C++
- Gestionar ocupación y liberación de lockers
- Simular sensores de ocupación
- Mostrar el estado de los lockers en tiempo real
- Crear una interfaz web para monitoreo

---

# Tecnologías Utilizadas

| Tecnología | Uso |
|---|---|
| C++ | Cliente y servidor |
| Sockets | Comunicación de datos |
| Python | Visualización |
| Streamlit | Dashboard |
| HTML/CSS/JS | Página web |
| GitHub | Control de versiones |

---

# Diagrama UML
<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/11f346b4-a9df-44a4-a042-6b14948e32f1" />

Diagrama UML corregido 
file:///C:/Users/Yoshiramayorque3/Downloads/uml_smartlocker_completo.svg

---

# Arquitectura del Sistema

```text
[Cliente C++]
Genera códigos de paquetes
        ↓
     Socket
        ↓
[Servidor C++]
Procesa lógica del sistema
        ↓
[Visualizador Python]
Estado en tiempo real
        ↓
[Página Web]
Monitoreo del sistema


