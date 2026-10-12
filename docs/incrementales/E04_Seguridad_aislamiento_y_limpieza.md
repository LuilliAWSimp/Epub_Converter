# E04 — Seguridad local, aislamiento de conversiones y limpieza

**Base:** proyecto `Epub_Converter-main.zip` con incrementales **E01 → E02 → E03** aplicados, en ese orden. Este ZIP es sólo un parche, no un proyecto completo.

## Objetivo

Asegurar la interfaz de conversión para uso local, impedir que trabajos simultáneos mezclen salida estándar o estado interno y evitar crecimiento indefinido de temporales/exportaciones. No cambiar el aspecto visual ni los flujos E01/E02/E03.

## Cambios

### Acceso y seguridad (`gui.py`, `converter/local_security.py`)

- Flask sólo escucha en `127.0.0.1:7474` (antes `0.0.0.0`). No se puede usar como servicio para otros dispositivos de red con la configuración predeterminada.
- Se rechazan hosts fuera de `localhost`, `127.0.0.1`, `::1`, direcciones remotas que no sean loopback y solicitudes con origen cruzado. Con ello se mitigan DNS rebinding y CSRF.
- Los POST desde la interfaz agregan `X-Requested-With: XMLHttpRequest`. Los clientes automatizados locales que invoquen la API deberán enviar este encabezado. No se habilita CORS.
- Se agregaron encabezados `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` y `Cache-Control: no-store` para API.
- `tesseract_cmd` enviado por formulario HTTP se **ignora** por completo. OCR autodetecta un ejecutable funcional en el equipo. La opción `--tesseract-cmd` de **consola** continúa disponible como antes.
- Archivo PDF requiere extensión `.pdf`; portada admite JPG, PNG o WEBP. Se escapan los nombres de archivos al mostrarlos en la interfaz para impedir HTML no deseado.
- Estado de trabajos ya no expone `output_path` ni `job_dir` al navegador; sólo estado, resultado, estadísticas y log.

### Procesos independientes (`gui.py`, `converter/job_worker.py`)

- Cada conversión usa un proceso Python separado invocado con `sys.executable` (sin `shell=True`).
- El proceso hijo aplica el flujo completo existente: extracción, OCR, limpieza, capítulos, comprobaciones E02 y EPUB.
- El proceso padre recibe logs por una tubería exclusivamente del proceso correspondiente. **No cambia `sys.stdout` global ni recarga `pdf2epub`**, evitando mezcla de registros, conflictos de Tesseract y recargas compartidas.
- Se aceptan hasta **2 conversiones en ejecución**; una tercera solicitud devuelve HTTP `429` con explicación legible. La interfaz vuelve a habilitar el botón cuando el inicio es rechazado.
- Si un trabajo excede **2 horas**, se detiene el proceso hijo y registra error.
- Sólo después de generar y validar correctamente el EPUB se publica en `gui_data/exports/`. Un candado protege la elección del nombre para que dos conversiones no sobrescriban sus resultados.
- El identificador de trabajo sigue siendo aleatorio e imposible de adivinar de forma práctica (UUID v4). El seguimiento del trabajo sigue funcionando desde la interfaz.

### Retención automática (`gui.py`)

- Al finalizar cualquier conversión, sea exitosa o con error, se **eliminan inmediatamente** el PDF subido, la portada temporal, la configuración del trabajo y el EPUB de trabajo; sólo se conserva el EPUB final validado.
- Los EPUB finales se conservan en `gui_data/exports/` hasta **7 días**, salvo que el conjunto supere **2 GiB**, en cuyo caso se eliminan primero los más antiguos.
- Los directorios de trabajo huérfanos y los archivos de `gui_data/temp/` con más de **24 horas** se eliminan periódicamente. Las carpetas de trabajos activos se excluyen de la limpieza.
- El estado en memoria de trabajos terminados se purga después de 7 días. Después de reiniciar Flask, los trabajos anteriores no aparecen en la API; los EPUB guardados permanecen en exports hasta alcanzar su retención.
- La limpieza se activa al recibir solicitudes locales, como máximo cada 15 minutos. **No es una tarea en segundo plano**: si el servidor no recibe solicitudes, la limpieza se ejecuta al siguiente acceso.

**Advertencia:** `gui_data/exports/` es una carpeta de descargas **temporales**, no un archivo de almacenamiento permanente. Descarga o mueve a otra carpeta cualquier EPUB que desees conservar antes de los 7 días o de que se alcance el límite global. No coloques EPUB personales en esa carpeta.

## Archivos del incremental

```text
gui.py
converter/job_worker.py
converter/local_security.py
tests/test_e04_security_jobs_cleanup.py
docs/incrementales/E04_Seguridad_aislamiento_y_limpieza.md
```

## Instalación

1. Respaldar el proyecto. Es indispensable tener instalados E01, E02 y E03.
2. Descomprimir `Incremental_E04_Epub_Converter.zip` en la raíz del proyecto donde se encuentra `gui.py`, permitiendo reemplazar ese archivo.
3. Ejecutar normalmente `run_gui_autoinstall.bat` en Windows o `python gui.py` con las dependencias instaladas.
4. La página se abrirá en `http://127.0.0.1:7474`. También se puede visitar `http://localhost:7474`.
5. No es necesario cambiar `.env`, `requirements.txt` ni los archivos de Tesseract.

## Comprobaciones dirigidas en Windows

1. Convertir un PDF con `OCR desactivado`, confirmar la descarga e inspeccionar el EPUB.
2. Convertir dos PDF simultáneamente desde dos pestañas; verificar que cada trabajo tiene su propio registro y archivo, sin mensajes del otro trabajo.
3. Intentar una tercera conversión mientras otras dos estén ejecutándose; comprobar que informa del límite y permite reintentar.
4. Abrir `gui_data/jobs/` después de finalizar ambas conversiones y verificar que ya no quedan las copias temporales de esos trabajos.
5. Revisar `gui_data/exports/` y descargar el EPUB final; preservar fuera de esa carpeta los libros que quieras conservar.
6. Comprobar que `http://127.0.0.1:7474` abre en el equipo anfitrión, pero que un equipo de la red no puede entrar al puerto mediante la IP LAN del servidor.
7. Verificar que OCR `auto`/`force` sigue usando una instalación **funcional** de Tesseract y los idiomas seleccionados. El Tesseract incluido podría requerir DLL en Windows (pendiente desde E01).

## Validación realizada

- **42/42 pruebas automatizadas**: 33 acumuladas de E01–E03 y 9 pruebas nuevas de E04.
- Prueba con **dos procesos de conversión reales simultáneos**: EPUB con contenido, validación interna correcta, logs separados y PDF temporales eliminados; `sys.stdout` del servidor se mantuvo intacto.
- Pruebas de host, cliente remoto, origen cruzado, solicitud sin encabezado anti-CSRF, cupo de trabajos, ignorar `tesseract_cmd`, ocultar rutas internas y limpieza segura con trabajo activo.
- Se reutilizó el motor con sus pruebas de extracción, OCR y capítulos originales.
- **Limitación de entorno:** Flask no está instalado aquí y no fue posible verificar con navegador/servidor Flask reales. Se probaron la lógica de las rutas con sustitutos controlados y los procesos de conversión con ejecuciones reales del motor Python.

## Fuera de alcance

- E05: optimizaciones para PDF grandes, rendimiento de imágenes y progreso detallado.
- E06: pruebas en lectores EPUB, EPUBCheck y UX avanzada.
- No se implementó servicio accesible por LAN ni cuentas de usuario: el producto sigue siendo una aplicación **exclusivamente local**.

## Commit sugerido (GitHub Desktop)

`E04: asegurar interfaz local y aislar conversiones con limpieza automática`
