# E02 — Integridad del texto y validación del EPUB

**Base obligatoria:** `Epub_Converter-main.zip` con el incremental **E01** ya aplicado.

## Objetivo

Eliminar la pérdida silenciosa de párrafos que se presentaba en PDF con secuencias numéricas repetidas, preservar páginas narrativas cortas, generar XHTML correctamente escapado y verificar el EPUB antes de publicar el resultado.

## Fallo reproducido y corregido

**Antes de E02:** un PDF narrativo de 5 páginas con 8 párrafos por página (`Este es el parrafo 1 de la pagina 1...`, `Este es el parrafo 2...`, etc.) producía 5 capítulos detectados pero **0 documentos XHTML de capítulos**: la normalización convertía todos los números en `<PAGE_NUM>` y clasificaba la prosa como encabezado/pie repetido. Aun así la aplicación mostraba éxito.

**Después de E02:** se preservan **40 párrafos narrativos**, se escriben **5 XHTML** de capítulos y la validación confirma que ninguno de esos párrafos falta en la lectura.

## Modificaciones

- `converter/text_utils.py`
  - La detección de encabezados y pies ya no reemplaza indiscriminadamente cifras de frases legítimas. Solo reconoce formatos explícitos de numeración marginal (`Página 5`, `5`, `Nombre | 5`).
  - Solo elimina candidatos en las dos primeras o las dos últimas líneas no vacías de cada página, no en el cuerpo.
  - Para repeticiones textuales exige una línea breve que no parezca una oración terminada.
  - Conserva cifras y frases narrativas similares en páginas consecutivas.
- `converter/chapters.py`
  - Retira el descarte general de una página con 1–2 párrafos cortos. Antes una frase de menos de ~70 caracteres podía descartarse al considerarse «separador visual».
- `converter/epub_writer.py`
  - Escapa correctamente caracteres `&`, `<`, `>` de títulos y metadatos, además de comillas de atributos XML.
  - Ajusta el enlace «Inicio» del OPF al primer documento real del libro (no supone que exista `Text/001.xhtml`).
  - Genera primero en un archivo temporal, comprueba el ZIP/XML/XHTML, comprueba todos los párrafos emitidos y **solo entonces** publica el EPUB definitivo con reemplazo atómico.
  - Ante un fallo no sobrescribe un EPUB anterior válido y limpia el temporal.
- `converter/integrity.py` (**nuevo**)
  - Detecta páginas de texto abundante vaciadas durante la limpieza.
  - Verifica que no falten párrafos narrativos largos tras separar capítulos, respetando las páginas explícitamente excluidas (TOC y auxiliares).
  - Valida internamente el archivo EPUB: tipo MIME/orden del ZIP, XML/XHTML parseable, `manifest`, `spine`, índice NCX, archivos referenciados y multiplicidad de párrafos (incluidos duplicados legítimos).
  - La validación falla explícitamente si el EPUB solo contiene la portada y no contiene capítulos ni ilustraciones de lectura.
- `pdf2epub.py` y `gui.py`
  - Integran ambas verificaciones de integridad en el flujo por consola y en la ruta de procesamiento del servidor Flask, respectivamente.
- `tests/test_e02_integrity.py` (**nuevo**)
  - 12 pruebas de regresión de contenido, errores XHTML, EPUB malformados, portada sola, limpieza y preservación de archivos previos; incluye prueba de punta a punta con PDF sintético de cinco páginas.

## Instalación de este incremental

1. Hacer copia de seguridad del proyecto.
2. Confirmar que **E01** está instalado.
3. Extraer `Incremental_E02_Epub_Converter.zip` **sobre la raíz que contiene `pdf2epub.py`** (no sobre su carpeta padre); conservar las rutas relativas de `converter/`, `tests/` y `docs/incrementales/`.
4. Sustituir los archivos coincidentes. No requiere cambios en `.env` ni nuevas dependencias.
5. Ejecutar las pruebas y luego iniciar normalmente la aplicación.

## Validación local

```sh
python -m unittest discover -s tests -v
python pdf2epub.py "ejemplo.pdf" -o "ejemplo.epub" --ocr off
```

Resultados con E01 + E02:

- **19/19 pruebas correctas**, incluidas 7 pruebas heredadas de E01.
- PDF numérico de 5 páginas: **40 párrafos en 5 capítulos** (antes 0 capítulos XHTML).
- PDF narrativo de 5 páginas: **40 párrafos** conservados.
- PDF con ilustración: imagen incrustada y ambos párrafos conservados.
- XML con caracteres especiales validado; si el resultado XML está mal formado o le faltan archivos, se detiene con un error verificable.
- Si falla una exportación, una versión anterior del mismo nombre permanece intacta.

La prueba OCR real de E01 pasó nuevamente en Linux. El entorno de pruebas no tiene Flask ni Tesseract para Windows; por ello **no se inició la GUI** y **no se probó el OCR en Windows**. La modificación de `gui.py` se limitó a conectar las comprobaciones de integridad, sin cambiar la página HTML ni los estilos.

**Alcance de la validación:** es un validador estructural interno, **no** una certificación completa con EPUBCheck. Algunos PDF con maquetaciones complicadas pueden necesitar ajustes adicionales en la clasificación de capítulos (E03).

## Fuera de alcance / pendiente

- **E03**: conectar controles OCR de la UI; revisar detección de capítulos/subtítulos para libros con títulos ambiguos.
- **E04**: seguridad y concurrencia del servidor, archivos temporales generales.
- **E05**: optimizaciones grandes e ilustraciones complejas.
- **E06**: validación externa con EPUBCheck y pruebas adicionales de compatibilidad.

## Archivos del incremental

```text
pdf2epub.py
gui.py
converter/text_utils.py
converter/chapters.py
converter/epub_writer.py
converter/integrity.py
tests/test_e02_integrity.py
docs/incrementales/E02_Integridad_texto_y_EPUB.md
```

## Commit sugerido (GitHub Desktop)

`E02: preservar texto y validar integridad antes de publicar EPUB`
