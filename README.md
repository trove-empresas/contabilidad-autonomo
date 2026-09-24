# contabilidad-autonomo

App local para que un autónomo en España gestione sus facturas, su IVA y su
IRPF: sube facturas, extrae sus datos, las clasifica a efectos de IVA y
prepara los resúmenes trimestrales (modelos 303 y 130).

> **Estado:** en preparación. Todavía no hay código de la app.

- Visión y etapas: [`docs/producto.md`](docs/producto.md)
- Decisiones: [`docs/decisiones.md`](docs/decisiones.md)
- Tecnología: Python + SQLite + interfaz web local (FastAPI, Jinja, htmx).
  Ver [`docs/propuesta-tecnica.md`](docs/propuesta-tecnica.md).

## Configurar la clave de API de Anthropic

La app usa un modelo de Anthropic para leer las facturas e interpretar las
preguntas. Necesita una clave de API, que se guarda **solo en tu equipo**,
en un archivo `.env`. Ese archivo está excluido del repositorio
(`.gitignore`), así que nunca se sube a GitHub.

1. **Consigue una clave** en <https://console.anthropic.com/>, en el apartado
   *API Keys*. Empieza por `sk-ant-`. Cópiala: solo se muestra una vez.
2. **Crea el archivo `.env`** en la carpeta raíz del proyecto a partir de la
   plantilla:

   ```bash
   cp .env.example .env
   ```

3. **Pega la clave** en `.env`, sin comillas ni espacios:

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

4. **Comprueba que Git no lo ve.** Este comando debe mostrar `.env`; si no
   muestra nada, no sigas y avisa:

   ```bash
   git check-ignore .env
   ```

Si la clave se filtra (por ejemplo, se sube por error o se pega en un
issue), **revócala enseguida** en la consola de Anthropic y crea otra. Borrar
el archivo del repositorio no basta: queda en el historial.

### Otras opciones de `.env`

| Variable | Qué hace | Por defecto |
|---|---|---|
| `ANTHROPIC_API_KEY` | Clave de API de Anthropic. Obligatoria. | — |
| `UMBRAL_CONFIANZA` | Confianza mínima (0 a 1) para que una factura entre en los cálculos sin que la confirmes. | `0.90` |

## Dónde quedan tus datos

Todo se guarda en la carpeta `datos/` (base de datos, facturas subidas y
copias de seguridad en `datos/copias/`). Está excluida del repositorio. Las
copias están en el mismo disco que la base de datos: para protegerte de una
avería del equipo, copia de vez en cuando `datos/` a otro soporte.
