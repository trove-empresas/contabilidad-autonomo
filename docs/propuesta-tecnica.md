# Propuesta técnica

> **Estado:** propuesta. No hay nada implementado. La decisión es de Gonzalo;
> cuando la tome, se registra en [`decisiones.md`](decisiones.md).

## Requisitos que condicionan la elección

- **Local:** funciona en el equipo del usuario; los datos no salen de él salvo
  la llamada al modelo de IA para extraer datos o interpretar preguntas.
- **Fácil de mantener:** pocas piezas, un solo lenguaje si es posible,
  dependencias estables.
- **Bien testeable:** el núcleo fiscal (clasificación, 303, 130, 390, 347) es
  código puro sin IA ni interfaz, probado con facturas ficticias.
- **Trazable:** cada importe calculado se puede rastrear hasta las facturas de
  origen; cada regla fiscal lleva norma y fecha.

En las tres opciones la arquitectura de fondo es la misma:

```
facturas (PDF/imagen) ──► extracción (IA) ──► revisión/confirmación (usuario)
                                                      │
                                                      ▼
                          base de datos local (SQLite) ◄── núcleo fiscal
                                                      │    (código puro, probado)
                                                      ▼
                                   resúmenes 303/130 · consultas con citas
```

Lo que cambia es el lenguaje y cómo se presenta la interfaz.

---

## Opción A — Python + SQLite + interfaz web local (FastAPI + HTML sencillo)

Un único programa en Python que se arranca en el equipo y se usa desde el
navegador en `localhost`. Interfaz con plantillas HTML (Jinja) y algo de
interactividad ligera (htmx), sin framework de frontend.

**Pros**
- Un solo lenguaje para todo: extracción, reglas fiscales, base de datos e
  interfaz.
- `pytest` es muy cómodo para probar el núcleo fiscal con tablas de casos
  (factura ficticia → resultado esperado).
- `decimal.Decimal` para importes exactos; buen soporte para PDF (pypdf,
  pdfplumber) y SDK oficial de Anthropic.
- Poca superficie: sin compilación de frontend ni empaquetado complejo.
- Es el stack que mejor maneja Claude de forma autónoma y el más fácil de
  leer para quien revise el código.

**Contras**
- Interfaz más sobria que una SPA; para una app de uso personal suele bastar.
- Distribuirla como "doble clic" requiere algo más (p. ej. `uv` o un
  empaquetador); para uso propio basta con un comando.
- Tipado opcional: hay que imponer `mypy`/`pyright` para que ayude de verdad.

## Opción B — TypeScript de extremo a extremo (Node + SQLite + React/Vite)

Servidor local en Node (p. ej. Hono o Fastify) con SQLite y una interfaz React
servida en `localhost`.

**Pros**
- Tipado estricto en todo el código, compartido entre servidor e interfaz.
- Interfaz más rica e interactiva (útil para la pantalla de revisión de
  facturas dudosas).
- Buenas herramientas de prueba (Vitest, Playwright) y SDK oficial de
  Anthropic.

**Contras**
- Más piezas que mantener: bundler, frontend, backend, dependencias npm que
  cambian con frecuencia.
- Los importes necesitan una librería decimal (JavaScript no tiene decimales
  exactos nativos); es fácil cometer errores con `number`.
- Más código para la misma funcionalidad que en la opción A.

## Opción C — App de escritorio con Tauri (Rust + interfaz web)

Aplicación de escritorio instalable, con núcleo en Rust y la interfaz en
HTML/TypeScript dentro de una ventana nativa.

**Pros**
- Se siente como una app de verdad: instalable, sin terminal ni navegador.
- Rust da mucha seguridad en el núcleo de cálculo (tipos, sin nulos) y
  ejecutables pequeños.

**Contras**
- Dos lenguajes (Rust y TypeScript) y una cadena de compilación exigente.
- Curva de aprendizaje y mantenimiento más altos; iteración más lenta.
- Probar la interfaz de escritorio es más laborioso que probar una web local.
- La ventaja principal (instalador) no aporta mucho a un único usuario.

---

## Comparación rápida

| Criterio                    | A · Python | B · TypeScript | C · Tauri |
|-----------------------------|:----------:|:--------------:|:---------:|
| Funciona en local           | ✅         | ✅             | ✅        |
| Facilidad de mantenimiento  | Alta       | Media          | Baja      |
| Testeabilidad del núcleo    | Alta       | Alta           | Alta      |
| Importes exactos            | Nativo     | Con librería   | Con librería |
| Riqueza de la interfaz      | Media      | Alta           | Alta      |
| Piezas / lenguajes          | 1          | 1 (varias capas) | 2       |

## Recomendación

**Opción A (Python + SQLite + interfaz web local).** Es la que mejor cumple
los tres requisitos a la vez: un solo lenguaje, pocas dependencias, decimales
exactos de serie y un núcleo fiscal fácil de probar con casos ficticios. La
interfaz sencilla es suficiente para v1 (subir, revisar, ver el trimestre) y,
si más adelante hace falta una pantalla de revisión más rica, se puede añadir
sin tocar el núcleo.

Si la prioridad fuera una interfaz muy pulida desde el principio, la opción B
sería la alternativa razonable. La C solo compensa si se quiere distribuir la
app a otros usuarios como programa instalable.

## Pendiente de decidir (además del stack)

- Umbral de confianza a partir del cual una factura requiere confirmación.
- Formato de entrada admitido en v1 (PDF con texto, PDF escaneado, foto,
  Facturae XML).
- Dónde se guardan los datos locales (carpeta `datos/`, ya excluida en
  `.gitignore`).
