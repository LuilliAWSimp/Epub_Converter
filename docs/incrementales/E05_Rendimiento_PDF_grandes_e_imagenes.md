# E05 — Rendimiento en PDF grandes y reutilización segura de ilustraciones

**Base obligatoria:** `Epub_Converter-main.zip` con **E01 → E02 → E03 → E04** ya aplicados. Este ZIP es un **incremental**, no el proyecto completo. Se aplica copiando los archivos del ZIP en la raíz del proyecto y aceptando reemplazos.

## Objetivos

1. Evitar acumular todos los objetos de diseño `LTPage`/`LTTextContainer` de `pdfminer` antes de extraer el texto.
2. Reducir decodificaciones y recodificaciones cuando un PDF utiliza una misma imagen (`xref`) muchas veces.
3. Conservar **todas las apariciones** de una ilustración, sin almacenar varias veces sus mismos bytes en el EPUB.
4. Evitar reabrir el PDF una vez por página reconocida mediante OCR y acotar los bitmaps de páginas enormes.
5. Preservar el comportamiento público y la validación de integridad E02.

## Cambios por archivo

### `converter/pdf_extract.py`

**Extracción de texto con almacenamiento intermedio acotado**

- Se procesa `pdfminer.high_level.extract_pages()` página a página, sin ejecutar `list(extract_pages(...))`.
- Se acumulan únicamente los contadores de encabezados/pies de página y el resultado final `pages_text`.
- Para mantener la detección original de encabezados repetidos, los bloques de texto se guardan temporalmente en `tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)`. Los datos se serializan por página y pasan automáticamente a un archivo temporal en disco si sobrepasan los 4 MiB. Se eliminan al cerrar el temporal, también ante excepciones.
- La misma pasada alimenta el conteo de encabezados; luego se reproducen los bloques del temporal para construir el texto final.
- Si pdfminer falla después de leer algunas páginas, el fallback de `pypdf` **descarta el resultado parcial** antes de volver a extraer, para evitar páginas duplicadas.
- Se emite progreso cada 100 páginas: `[PDF E05] Páginas analizadas: 100/NNN`.

**Caché de imágenes por xref**

- Una misma imagen PDF puede aparecer en muchas páginas. La primera aparición se decodifica, filtra y convierte a JPEG compatible; las siguientes reutilizan sus bytes y el análisis ya calculado.
- La caché mantiene como máximo **24 MiB** y **128 entradas**, expulsando primero las menos recientes. No guarda los bitmaps RGB decodificados.
- La caché es **local a la extracción de ese PDF**, no se comparte entre trabajos; tampoco se comparte en procesos Flask E04.
- **No** se reutilizan las coordenadas, `page_idx`, rótulo, indicador de página ilustrada ni otros metadatos contextuales: se crean para cada aparición individual.
- Para imágenes PDF sin xref se conserva la extracción normal mediante renderizado del área, sin asumir que dos regiones son idénticas.
- El fallback `pypdf` sigue disponible.

**OCR de documentos de varias páginas**

- `apply_ocr_to_pages()` abre un único `fitz.Document` para todas las páginas pendientes de reconocimiento y lo cierra siempre al salir.
- `_render_page_to_png_bytes` sigue siendo utilizable por separado; internamente admite la referencia de un documento abierto.
- El renderizado OCR tiene un límite conservador de **20 millones de píxeles por página**. Reduce el DPI proporcionalmente para pliegos grandes y explica el error si ni siquiera a 72 DPI caben dentro del límite.
- En modo `force` los errores continúan siendo fatales. En modo `auto` se conserva la extracción original y se registra advertencia si no se puede abrir el PDF para OCR.
- No cambia el DPI solicitado para páginas normales ni los idiomas y modos OCR definidos en E03.

### `converter/epub_writer.py`

- Identifica JPEGs idénticos por media type + SHA-256 y confirma la igualdad de bytes antes de fusionarlos.
- El EPUB almacena el recurso una sola vez en `OEBPS/Images/` y lo declara una sola vez en el manifest de `content.opf`.
- Todas las ocurrencias mantienen su lugar y leyenda; se distinguen mediante un identificador interno de aparición separado del nombre compartido del archivo.
- Los diccionarios de imágenes que recibe `create_epub()` no se renombran ni modifican.
- Se mantiene el empaquetado atómico y `validate_epub_archive()` de E02.

## Validaciones efectuadas

- **53/53 pruebas automatizadas**: 42 de E01–E04 y **11 nuevas** para E05.
- Las pruebas E05 comprueban páginas y texto preservados, progreso de 100 páginas, fallback seguro ante error a mitad de PDF, imagen repetida procesada sólo una vez, preservación de bbox/leyenda/tipo contextual, referencias a una misma imagen en varios lugares del XHTML, deduplicación del manifest, apertura única para OCR, reducción segura de DPI y errores de OCR en modo automático.
- Conversión real en CLI de un documento de texto de 5 páginas: 5 capítulos, 40 párrafos; EPUB válido.
- Conversión real en CLI de un documento ilustrado: EPUB válido con ilustración.
- Prueba de EPUB de 90 páginas y 90 apariciones de la misma ilustración: el EPUB conserva las 90 referencias con un solo recurso JPEG.

### Comparación de rendimiento (referencial)

Prueba controlada en el mismo contenedor Linux, Python y dependencias; PDF **sintético** de **90 páginas** y una misma ilustración reutilizada en cada página. Medición de *extracción de texto e imágenes* en procesos nuevos con `time.perf_counter` y `resource.ru_maxrss`:

| Medida | E04 | E05 |
| --- | ---: | ---: |
| Tiempo de extracción | 7.017 s | 2.984 s |
| Pico de memoria residente (proceso) | 316.5 MiB | 162.6 MiB |
| Decodificaciones/recodificaciones JPEG de ilustración repetida | 90 | 1 |

Con el mismo conjunto ilustrado y un capítulo de texto de prueba, comparación del EPUB final:

| Medida | E04 | E05 |
| --- | ---: | ---: |
| Tamaño EPUB | 6,009.6 KiB | 143.7 KiB |
| Recursos `Images/img*.jpg` dentro del EPUB | 90 | 1 |
| Apariciones `src="../Images/img..."` dentro del XHTML | 90 | 90 |

**Importante:** estas cifras muestran la ventaja con imágenes **reutilizadas**. El tiempo, memoria y tamaño de archivos con ilustraciones todas diferentes, PDFs escaneados o maquetaciones complejas pueden variar considerablemente. No se garantiza el mismo porcentaje de mejora en otros documentos. El texto final y las imágenes conservadas continúan ocupando memoria mientras se prepara el EPUB: esto no es una arquitectura completamente streaming.

## Archivos del parche

```text
converter/pdf_extract.py
converter/epub_writer.py
tests/test_e05_large_documents.py
docs/incrementales/E05_Rendimiento_PDF_grandes_e_imagenes.md
```

## Instalación

1. Respaldar el proyecto antes de aplicar el ZIP.
2. Confirmar que E01, E02, E03 y E04 están instalados, en ese orden.
3. Extraer `Incremental_E05_Epub_Converter.zip` **sobre la raíz** donde se ubica `pdf2epub.py`; reemplazar únicamente los dos archivos `converter` indicados.
4. Mantener los mismos archivos de configuración y dependencias. No se requiere cambiar `.env`, `requirements.txt` ni `tesseract`.
5. Iniciar el programa como antes (`run_gui_autoinstall.bat` o CLI).

## Validación dirigida en Windows

1. Convertir un PDF narrativo extenso con OCR desactivado y comprobar que conserva capítulos y texto.
2. Convertir un PDF con ilustraciones que se repitan en distintas páginas. Verificar visualmente las apariciones, el índice y el EPUB en el lector habitual.
3. Abrir el EPUB como ZIP si se desea inspeccionar `OEBPS/Images` y comprobar que no haya JPEGs idénticos por repetición innecesaria.
4. Probar OCR `auto` y `force` con documentos grandes; confirmar advertencias de memoria cuando un pliego supera el límite y que la conversión `force` no oculte errores.
5. Revisar los logs cuando se hayan procesado más de 100 páginas para comprobar las líneas de progreso.
6. Confirmar que E04 sigue aislando dos conversiones simultáneas y limpiando temporales.

## Fuera de alcance y limitaciones

- No se cambió la interfaz Flask ni la conexión local E04.
- No se alteraron los estilos, portada, detección de capítulos, selecciones OCR ni archivos de configuración.
- No se añadieron dependencias nuevas ni cambios a `.env` o `requirements.txt`.
- No se ejecutó Flask en navegador real ni se validó el instalador Windows/Tesseract de Windows en este entorno; continúan como pruebas dirigidas.
- La validación EPUB E02 no sustituye una revisión con EPUBCheck en E06.
- E06: compatibilidad en lectores reales, diagnósticos más claros y pruebas de EPUBCheck/interfaz.

## Commit sugerido (GitHub Desktop)

`E05: optimizar PDF grandes y reutilizar ilustraciones sin perder apariciones`
