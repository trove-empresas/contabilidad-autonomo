# Registro de decisiones

Aquí se apuntan las decisiones relevantes del proyecto (técnicas, fiscales o de
producto), de la más reciente a la más antigua. Una decisión no se borra: si
cambia, se añade una nueva que la sustituye y se indica en ambas.

## Formato

```markdown
## AAAA-MM-DD — Título corto de la decisión

- **Decisión:** qué se ha decidido, en una o dos frases.
- **Motivo:** por qué.
- **Alternativas descartadas:**
  - Alternativa A: por qué no.
  - Alternativa B: por qué no.
- **Estado:** vigente | sustituida por «AAAA-MM-DD — …»
```

## Decisiones

## 2026-09-24 — La clave de API de Anthropic va en `.env`

- **Decisión:** la app lee la clave de la variable `ANTHROPIC_API_KEY`, que
  se define en un archivo `.env` en la raíz del proyecto (excluido por
  `.gitignore`). Nunca se escribe en el código, en ejemplos ni en commits.
  El repositorio solo incluye `.env.example`, con los nombres de las
  variables y la clave vacía. Cómo configurarla: ver `README.md`.
- **Motivo:** línea roja de `criterio` (ningún secreto en el código ni en el
  historial). `.env` es el mecanismo estándar y ya estaba excluido.
- **Alternativas descartadas:**
  - Clave en un archivo de configuración versionado: expone el secreto.
  - Llavero del sistema operativo (keyring): más seguro, pero añade
    dependencias y complica la configuración inicial; se puede reconsiderar.
- **Estado:** vigente.

## 2026-09-24 — Datos en `datos/` y copia de seguridad local automática en v1

- **Decisión:** todos los datos de la app (base de datos SQLite, facturas
  subidas, copias) viven en `datos/`, excluida del repositorio. En v1 la app
  hace una copia de seguridad automática de la base de datos en
  `datos/copias/`:
  - al arrancar la app (como máximo una al día por este motivo), y
  - justo antes de cualquier operación que cambie datos en bloque
    (importación de varias facturas, confirmación masiva, migración del
    esquema).
  - La copia se hace con la API de copia en caliente de SQLite, no copiando
    el archivo a mano, para que no quede a medias si la base está en uso.
  - Nombre con fecha y hora (`AAAA-MM-DD_HHMMSS.sqlite3`). La app **no
    borra copias antiguas por su cuenta**; si ocupan demasiado, avisa y el
    usuario decide qué eliminar.
- **Motivo:** son datos fiscales que hay que conservar años; perder la base
  de datos por un error o una migración fallida sería grave. `criterio`
  prohíbe borrar datos, por eso no hay rotación automática.
- **Alternativas descartadas:**
  - Rotación automática (guardar solo las últimas N): borra datos sin
    permiso.
  - Copia en la nube: los datos saldrían del equipo; fuera de alcance.
  - Sin copia en v1: riesgo demasiado alto para datos fiscales.
- **Estado:** vigente.

## 2026-09-24 — Formatos de factura admitidos en v1

- **Decisión:** v1 admite:
  - **PDF con texto:** se extrae el texto del PDF y se envía al modelo.
  - **PDF escaneado** (sin capa de texto): las páginas se convierten en
    imágenes y se leen con la lectura de imágenes del modelo.
  - **Fotos** (JPG, PNG y HEIC del móvil): lectura de imágenes del modelo.

  **Facturae XML** queda para más adelante. El detalle de cómo se envía
  cada formato al modelo se concreta al implementar y, si cambia algo
  relevante, se registra aquí.
- **Motivo:** cubre lo que llega en la práctica (PDF por correo y fotos de
  tickets o facturas en papel) sin montar un OCR propio.
- **Alternativas descartadas:**
  - OCR local (p. ej. Tesseract): otra pieza que mantener y peor con fotos
    torcidas o mal iluminadas.
  - Facturae XML en v1: es poco habitual entre los proveedores de un
    autónomo; se deja para una versión posterior.
- **Estado:** vigente.

## 2026-09-24 — Umbral de confianza inicial: 0,90, configurable

- **Decisión:** cada factura tiene una confianza entre 0 y 1, igual a la
  **más baja** de sus campos clave (NIF de emisor y receptor, fecha, número,
  base, tipo y cuota de IVA, retención, total y clasificación de IVA).
  - Si es **menor que 0,90**, la factura queda pendiente de confirmación y
    no entra en ningún cálculo.
  - El umbral se configura con `UMBRAL_CONFIANZA` en `.env` (por defecto
    `0.90`).
  - Además, una factura queda **siempre** pendiente, sea cual sea su
    confianza, si:
    - no cuadran los importes (suma de bases + suma de cuotas − retención
      ≠ total, con un margen de 1 céntimo por cada tipo de IVA, por
      redondeo);
    - algún NIF no supera la comprobación de su letra o dígito de control;
    - falta algún campo clave;
    - la clasificación es exenta, no sujeta o inversión del sujeto pasivo y
      es la primera vez que aparece ese proveedor con esa clasificación.
- **Motivo:** la confianza que declara un modelo no es una probabilidad
  fiable, así que el umbral se complementa con comprobaciones deterministas
  que no dependen de la IA. 0,90 es conservador: al principio se prefiere
  confirmar de más. Se calibrará con facturas reales, mirando cuántas
  pendientes resultan estar bien y cuántos errores pasan el umbral.
- **Alternativas descartadas:**
  - Confirmar todas las facturas: seguro, pero la app pierde utilidad.
  - Umbral más bajo (0,70–0,80): demasiado permisivo antes de calibrar.
  - Media de los campos en lugar del mínimo: un campo dudoso quedaría
    escondido por los demás.
- **Estado:** vigente (valor provisional, pendiente de calibrar).

## 2026-09-24 — Tecnología: Python + SQLite + web local (FastAPI, Jinja, htmx)

- **Decisión:** la app se construye en Python, con SQLite como base de datos
  local y una interfaz web que se usa desde el navegador en `localhost`,
  servida con FastAPI, plantillas Jinja y htmx para la interactividad.
  Decidido por Gonzalo (opción A de
  [`propuesta-tecnica.md`](propuesta-tecnica.md)).
- **Motivo:** un solo lenguaje, pocas dependencias, decimales exactos de
  serie (`decimal.Decimal`) y un núcleo fiscal fácil de probar con `pytest`
  y facturas ficticias.
- **Alternativas descartadas:**
  - TypeScript de extremo a extremo (Node + React): más piezas que mantener
    y decimales solo con librería.
  - App de escritorio con Tauri (Rust): dos lenguajes y mantenimiento más
    costoso; el instalador no aporta mucho a un único usuario.
- **Estado:** vigente.
