# PDF → EPUB Converter (Local Web Tool)

Herramienta local para convertir PDF a EPUB con interfaz web, enfocada
en libros narrativos (especialmente novelas ligeras e ilustradas).

------------------------------------------------------------------------

## ✨ Características

-   Interfaz web local (no depende de servicios externos)
-   Conversión PDF → EPUB optimizada para lectura
-   Detección automática de:
    -   Prólogo
    -   Capítulos
    -   Epílogo
    -   Afterword
    -   Historias extra
-   Preserva:
    -   estructura narrativa
    -   títulos y subtítulos de capítulos
    -   flujo del contenido
-   Manejo de imágenes:
    -   conserva ilustraciones relevantes
    -   elimina imágenes decorativas repetidas
-   OCR opcional para PDFs escaneados o con texto corrupto

------------------------------------------------------------------------

## 🧠 Enfoque del proyecto

Este convertidor no busca solo "sacar texto del PDF", sino:

-   evitar que la tabla de contenido se trate como texto real
-   separar correctamente capítulos
-   conservar títulos en lugar de convertirlos en párrafos normales
-   mantener una experiencia de lectura coherente en EPUB

------------------------------------------------------------------------

## 📁 Contenido del proyecto

-   `pdf2epub.py`: motor principal PDF → EPUB
-   `gui.py`: interfaz web local
-   `requirements.txt`: dependencias Python
-   `run_gui.bat`: lanzador automático (recomendado)
-   `run_cli_example.bat`: ejemplo por consola

------------------------------------------------------------------------

## 🚀 Uso rápido (recomendado)

1.  Ejecuta:

run_gui.bat

2.  El script:
    -   detecta Python
    -   crea entorno virtual (si no existe)
    -   instala dependencias automáticamente
    -   abre la interfaz web
3.  Usa el navegador para convertir tu PDF

------------------------------------------------------------------------

## 🔧 Mejoras recientes (importante)

### 🖼️ Manejo de imágenes mejorado

Antes: - EPUB se veía bien en PC - En móvil podían aparecer: - imágenes
negras - imágenes cortadas - bloques grises/negros

Ahora: - Imágenes funcionan correctamente en: - móvil - escritorio -
Eliminación de imágenes basura del PDF - Mejor compatibilidad entre
lectores EPUB

Tradeoff: - layout inicial de imágenes más controlado - menos
"compacto", pero mucho más estable

------------------------------------------------------------------------

### 🧹 Limpieza de headers/footers

-   Eliminación mejorada de líneas repetidas como:
    -   `Einherjar Project | 15`
-   Detección por patrón (no solo coincidencia exacta)

------------------------------------------------------------------------

### 📖 Mejora en títulos de capítulos

-   Detecta correctamente capítulos y secciones
-   Conserva subtítulos
-   Evita convertirlos en texto plano

------------------------------------------------------------------------

## ⚠️ Limitaciones

-   tablas complejas
-   fórmulas
-   PDFs tipo revista
-   maquetación en columnas

------------------------------------------------------------------------

## ⚙️ Tecnologías

-   Python
-   Flask
-   PyMuPDF / pdfminer / pypdf
-   Pillow
-   Tesseract OCR

------------------------------------------------------------------------

## 📌 Resumen

Una herramienta local PDF → EPUB pensada para libros narrativos, que:

-   reconstruye la estructura del libro
-   limpia artefactos del PDF
-   conserva capítulos y títulos
-   y ahora ofrece mejor compatibilidad entre dispositivos
