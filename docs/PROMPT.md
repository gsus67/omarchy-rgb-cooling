# Omarchy RGB & Cooling Manager — prompts por fases (v2)

Cómo usarlo: pega el **Bloque común** y después **una sola fase**. No pases a la siguiente fase sin revisar lo que entregó la anterior.

---

## Bloque común (va en todas las fases)

### Rol
Eres desarrollador senior de Linux (Arch/Omarchy, Quickshell/QML, C++/Qt6, HID/USB, hwmon, systemd y licencias libres). Trabajas en `~/Work/omarchy-rgb-cooling`, un plugin nativo de Omarchy para gestionar RGB y refrigeración desde la barra. Licencia del código propio: **GPL-3.0-or-later**.

### Lenguajes y stack (fijos salvo bloqueo justificado)
- **QML (Quickshell)**: la interfaz (widget de barra y panel).
- **C++20 + Qt6 (QtCore, QtNetwork)**: el núcleo `rgbcd`. Comprueba que haya compilador con soporte C++20, pkg-config y los módulos Qt necesarios; no deduzcas que están solo porque Quickshell use Qt6. Sigue el patrón de `bootstrap.py`/`native_build.py` de `~/Work/omarchy-trcc`: bloqueo de compilación, huella de fuentes y herramientas, sustitución atómica del binario y binario en `$XDG_STATE_HOME`. Las dependencias de pruebas se declaran por separado; CMake/ctest no son requisitos del patrón existente.
- **Python 3 (solo stdlib)**: bootstrap, instalador y pruebas de integración.
- **Bash** solo para envoltorios mínimos, y siempre pasando ShellCheck.
- Go no está instalado; no se usa salvo que demuestres que Qt6 no sirve para algo concreto.

### Arquitectura obligatoria
1. **La UI no tiene privilegios y nunca toca hardware.** Solo habla con `rgbcd` por un Unix socket en `$XDG_RUNTIME_DIR` (permisos 0600, se comprueba el UID del cliente con `SO_PEERCRED`).
2. **`rgbcd` es un servicio systemd `--user` sin root, activado por socket.** Lo activa una unidad `.socket` con `Accept=no`, `ListenStream=%t/omarchy-rgb-cooling.sock` y `SocketMode=0600`. Hay que validar `LISTEN_PID`/`LISTEN_FDS` y adoptar el descriptor con `QLocalServer::listen(qintptr)`; no se vuelve a enlazar ni se borra el socket que creó systemd. En cada conexión aceptada se comprueba `SO_PEERCRED` antes de procesar datos y se rechaza cualquier UID distinto del propio (esto no aísla procesos del mismo usuario). El bootstrap prepara ambas unidades y activa solo la `.socket`; no copia el arranque permanente de omarchy-trcc.
3. **`rgbcd` nunca escribe PWM ni registros de hardware.** El control de ventiladores se delega en un motor que ya tenga su propia seguridad (CoolerControl `coolercontrold`) o se deja en manos de BIOS/firmware. Las curvas no dependerán de que `rgbcd` esté vivo, pero eso no garantiza seguridad si cae el motor, se pierde un sensor, se suspende el equipo o se desconecta el dispositivo. Antes de habilitar escrituras hay que documentar, por canal, el comportamiento y la recuperación del motor/firmware, los límites físicos validados y el procedimiento para devolver el control. Que la API acepte un mínimo no demuestra que refrigere lo suficiente.
4. **Telemetría base sin motores:** temperaturas y RPM se leen directamente de `/sys/class/hwmon` (solo lectura, como usuario). Los motores solo añaden lo que hwmon no da.
5. **Un solo motor autorizado por dispositivo físico**, con una identidad adecuada a su bus: VID:PID no basta ni cubre PCI/I²C, y nunca se usan índices. Documenta las exclusiones configuradas en cada motor y bloquea escrituras si la identidad o la propiedad son dudosas.
6. **Conexión con motores:** por loopback (127.0.0.1/::1) o Unix socket. Nunca escuchar en interfaces externas. Las credenciales de los motores se guardan en archivos 0600; nunca en URLs ni en argumentos de línea de comandos.
7. **Excluido siempre:** el dispositivo `0416:5302` (Thermalright Trofeo) pertenece al plugin `omarchy-trcc`. Hay que excluirlo tanto del adaptador como de la detección y el control de los motores; si esa exclusión no se puede garantizar, se bloquea la combinación con omarchy-trcc.

### Reglas de seguridad
- Prohibido: sudo silencioso, ejecutar scripts remotos, reglas udev con `MODE="0666"`, ejecutar como root archivos de la carpeta del plugin (que el usuario puede modificar) y ejecutar comandos que lleguen desde la UI (solo un conjunto cerrado de operaciones, con parámetros validados).
- Si algo necesita root: un paso explícito que el usuario ejecuta él mismo, que instala copias propiedad de root, con hardening de systemd verificado con `systemd-analyze security`.
- Todo texto que venga de dispositivos o motores se muestra en QML como texto plano (`textFormat: Text.PlainText`), nunca como rich text.
- Cada corrección de seguridad lleva su test de regresión.

### Trabajo limpio y CI (desde el primer commit)
- Todo lo que el proyecto añade al sistema (archivos, unidades systemd, sockets, estado, caché, exclusiones configuradas en motores) queda registrado y `uninstall.sh` lo elimina por completo, sin tocar nada que existiera antes.
- Cuando se quita una función o un archivo, el siguiente bootstrap borra lo que dejaron las versiones anteriores (migración), y el test `tests/clean_uninstall.py` lo comprueba: instala en un HOME temporal, desinstala y falla si queda cualquier resto.
- Se trabaja en ramas y se entra a `main` solo por PR con squash merge y título limpio (`feat: ...`). `main` está protegido: solo se mergea con todos los checks en verde: Tests (Arch), Sanitizers (ASan + UBSan), Clean uninstall, Service hardening, ShellCheck, zizmor, CodeQL (c-cpp, python, actions).
- Actions fijadas por SHA, `permissions` mínimos y `persist-credentials: false`; nada de `pull_request_target`.
- Cada corrección de seguridad lleva su test de regresión; no se desactiva ni se relaja un check para pasar en verde.

### Reglas de verdad
- No inventes APIs, compatibilidad ni cifras. Cada dato técnico o de licencia lleva su fuente (URL o ruta local) y la marca **[V]** verificado, **[I]** inferido o **[NV]** no verificado.
- Estados de un dispositivo: `reconocido` → `soportado-upstream` → `probado-simulación` → `probado-físico`. Solo el último lo puede marcar el usuario tras probarlo él.
- No instales, desinstales ni modifiques nada del sistema sin preguntar antes; enseña antes el comando exacto.

### Parada
Al terminar el alcance de la fase, **o** al encontrar un bloqueo técnico, legal o de seguridad: detente y entrega un resumen (qué hiciste, qué verificaste, qué queda pendiente y qué decisiones necesitas del usuario). No empieces la fase siguiente.

---

## Fase 1 — Inventario y decisión (sistema y hardware en solo lectura; únicamente se permite crear docs/INVENTORY.md en el proyecto)

Objetivo: saber qué hay realmente antes de diseñar.

Haz (sin instalar nada, sin arrancar motores, sin escanear I²C/SMBus, sin escribir en hardware):
1. **Omarchy:** versión del paquete (`pacman -Q omarchy quickshell`) y contrato de plugins observado en `/usr/share/omarchy` (`omarchy-plugin-add`, `omarchy plugin validate`, tipos `bar-widget`/`panel`/`service`, `manifest.json` `schemaVersion`). Usa como referencia los tres plugins de `~/Work` (omarchy-tool, omarchy-trcc, omarchy-taskbar).
2. **Hardware visible:** `lsusb`, `lspci -nn`, `/sys/class/hwmon/*` (nombre, sensores, `pwm*_enable` en solo lectura), GPU y su driver. Para cada dispositivo: qué motor lo soporta según la documentación del proyecto original.
3. **Motores:** para OpenRGB, CoolerControl, liquidctl, OpenLinkHub, ckb-next, gloriousctl y rgb_keyboard:
   - licencia SPDX exacta del commit o versión actual;
   - clasificación por paquete y fecha: repos oficiales, AUR u otros repositorios. Base verificada: openrgb en extra; CoolerControl para Arch mediante AUR. Verifica nombres y versiones concretos antes de proponer comandos;
   - si funciona sin GUI;
   - cómo se habla con él (API/protocolo);
   - con qué otros motores choca (p. ej. CoolerControl ya usa liquidctl).

   OpenMouse/mouse-protocol solo se anotan (son una aplicación web y una librería WebHID AGPL); no se integran.
4. **Marketplace:** busca y cita la política publicada de omacom/omarchy-plugin-marketplace sobre servicios, binarios y privilegios. Si no existe o no es accesible, márcala [NV]; no inventes requisitos ni bloquees el MVP por esa ausencia.

Entrega `docs/INVENTORY.md` con:
- tabla de hardware → motor → estado;
- tabla de motores con licencias y fuentes;
- **propuesta de MVP:** el dispositivo RGB y el sensor/ventilador concretos de esta máquina, con lo mínimo que habría que instalar.

**Para aquí** y espera la aprobación del usuario.

---

## Fase 2 — MVP (monitorización + 1 RGB)

Requisito previo: el usuario aprobó el MVP de la fase 1 y, si hace falta, instaló él mismo el motor RGB elegido.

Alcance:
1. Estructura del repo copiando el patrón de omarchy-trcc: `manifest.json` (`bar-widget`), QML, `src/` (C++/Qt6), `bootstrap.py`, `native_build.py`, `tests/`, `install.sh`/`uninstall.sh` sin sudo.
2. `rgbcd`:
   - activación por socket;
   - API JSON delimitada por saltos de línea, con versión, identificador de petición, límites de tamaño y de conexiones, y timeout. QML usará `Quickshell.Io.Socket` con ruta absoluta, un parser de líneas y write/flush; como alternativa, `Process` ejecutará un cliente local con argumentos fijos y sin shell. Operaciones cerradas: `status`, `sensors`, `devices`, `lighting.get`, `lighting.set{device, color, brightness}`;
   - telemetría desde hwmon;
   - adaptador OpenRGB SDK binario sobre TCP (si OpenRGB es el motor elegido), con negociación de versión, validación de paquetes y servidor verificado en loopback. El protocolo documentado no tiene autenticación. Color estático y brillo en un solo dispositivo, activados únicamente según las capacidades del dispositivo y del modo; si el brillo se emula escalando el RGB, se indica. La identidad persistente se guarda aparte del identificador del protocolo: las versiones 0–5 usan índices y obligan a reconstruir el mapa cuando cambian los dispositivos.
3. Adaptadores con interfaz común y capacidades declaradas (`read`, `write`, `effects`, `fan-read`…). Cada adaptador implementa solo lo que soporta y devuelve `unsupported` para el resto.
4. **Modo demo** con hardware simulado (adaptador falso + árbol hwmon falso en un directorio temporal).
5. UI:
   - icono en la barra con la temperatura principal;
   - panel con **Dashboard** (temperaturas/RPM) y **Lighting** (selector de color y brillo).
   Colores y transparencia del tema de Omarchy, escalado HiDPI y navegación por teclado.
6. Hotplug mediante libudev y QSocketNotifier; comprueba libudev con pkg-config (aquí lo proporciona systemd-libs). Alternativa sin enlazar libudev: socket Linux `NETLINK_KOBJECT_UEVENT` con QSocketNotifier, distinguiendo eventos del kernel de eventos ya procesados por udev, validando el origen y reconciliando el inventario si se pierden eventos. Verifica que se reciben como usuario y que funciona con el hardening aplicado. Para hwmon, la lectura solo se hace mientras el panel o el widget lo piden, con un intervalo configurable (por defecto 2 s) y se detiene cuando nadie lo necesita.

Fuera de alcance: control de ventiladores, curvas, bombas, efectos, perfiles e instalación de motores.

Criterios de aceptación (con evidencia en el resumen):
- `omarchy plugin validate .` pasa. Además se verifica que el widget y el panel cargan de verdad en Omarchy, usando el contrato QML observado en los plugins existentes. Solo cuentan los errores atribuibles al plugin durante la prueba; un journal global limpio no es criterio. Activación, reactivación, permisos y rechazo de credenciales se prueban con integración real, además de con mocks.
- Tests: unitarios C++ (QtTest/ctest), integración en Python con el modo demo y prueba de que **en modo lectura no se hace ninguna escritura**.
- Medición real de RSS/CPU de `rgbcd` en reposo y activo (`/proc/<pid>/status`, `pidstat`), con los números tal cual salen.
- Cerrar el panel cancela su suscripción. Mientras la barra pida temperatura, `rgbcd` sigue activo. Sin suscripciones ni operaciones pendientes, sale a los 60 s; la `.socket` sigue activa y la siguiente petición lo vuelve a arrancar. Verifica ambos casos y que no quedan procesos duplicados.

---

## Fase 3 — Refrigeración delegada en CoolerControl

Requisito previo: el usuario instaló `coolercontrold` y validó en la fase 1 qué canales controla en su placa.

Alcance:
1. Adaptador para la API REST de `coolercontrold` (loopback). Fija la versión de coolercontrold y documenta desde su OpenAPI los métodos, rutas y esquemas de dispositivos, canales, perfiles, asignación de perfiles a canales, modos y reset/default. No confundas activar un modo con asignar un perfil. Usa preferentemente un token Bearer dedicado si esa versión lo soporta; la alternativa documentada es el login HTTP Basic de CCAdmin con cookie de sesión. No habilites escrituras con rutas o semánticas [NV].
2. Secciones **Cooling** y **Fan Curves**:
   - mostrar y editar curvas que **ejecuta CoolerControl**, no nuestro proceso;
   - cambiar el perfil activo;
   - volver a "automático/default".
3. Validación antes de enviar:
   - `rgbcd` valida toda curva y todo perfil/modo que se aplique: valores finitos, unidades, temperaturas ordenadas, límites térmicos y de duty, identidad de sensor/canal y antigüedad de las lecturas. Se aplican los límites físicos confirmados; si faltan, el canal queda en solo lectura. También se validan los perfiles ya existentes y todos los canales afectados por un modo;
   - **canales de bomba: nunca por debajo de su mínimo ni en 0 %**; si no se puede saber qué canal es la bomba, ese canal queda bloqueado en solo lectura;
   - histéresis y suavizado los aplica el motor si los soporta; si no, se documenta como limitación.
4. Recuperación:
   - si `coolercontrold` cae o deja de responder, la UI lo muestra y **no intenta tomar el control**;
   - documenta qué hace el propio motor al cerrarse o al suspender (con fuente);
   - `restore-auto` puede devolver `unsupported`.
5. Alertas térmicas: usa preferentemente las que ejecuta CoolerControl. Las alertas que calcule `rgbcd` solo funcionan mientras tenga la monitorización activa; muestra esa limitación y aplica histéresis y límite de frecuencia (notificación con `notify-send`).

Fuera de alcance: escribir PWM directamente, liquidctl como motor aparte (va a través de CoolerControl) y curvas calculadas por `rgbcd`.

Criterios de aceptación:
- tests con un `coolercontrold` simulado: caída, timeout, valores NaN, sensor desaparecido, RPM 0 y rechazo de valores inseguros;
- en hardware real, el usuario confirma él mismo cada canal antes de marcarlo `probado-físico`.

---

## Fase 4 — Ampliaciones y publicación

Solo lo que el inventario justifique para hardware real del usuario:
1. **Perfiles** (RGB + refrigeración) y sincronización opcional del color con el tema de Omarchy (al cambiar de tema, por evento, no por sondeo).
2. **Drivers / gestor de motores:**
   - muestra qué motores hacen falta para el hardware detectado, su licencia, si están en repo oficial o AUR, y el comando exacto de instalación;
   - **el plugin no instala nada él mismo**: el usuario copia y ejecuta el comando, o lo confirma en un paso explícito;
   - lleva un registro de lo que añadió el proyecto para poder desinstalarlo sin tocar paquetes previos.
3. Adaptadores extra (OpenLinkHub, ckb-next, gloriousctl, rgb_keyboard) **uno por PR**, cada uno con su análisis de licencia y conflictos. Con OpenLinkHub, nunca activar `manual:true` (desactiva su monitorización térmica).
4. Documentación: README, ARCHITECTURE, INSTALLATION, HARDWARE_SUPPORT (con los estados), BACKENDS, SECURITY, LICENSES (inventario SPDX incluidas las dependencias transitivas), CONTRIBUTING, CHANGELOG. Incluye cómo devolver el control a BIOS/motor paso a paso.
5. CI: tests en Arch, CodeQL (c-cpp, python, actions), ASan/UBSan, ShellCheck, zizmor, `systemd-analyze security` si hay unidades, test de QML en texto plano.
6. Preparación para el marketplace siguiendo su política verificada en la fase 1.
