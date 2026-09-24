# Producto

## Visión

Una app **local** para un autónomo en España que le permita llevar al día sus
facturas y sus impuestos sin depender de hojas de cálculo ni de servicios en
la nube, y con información que siempre se pueda verificar.

La app permite:

- **Subir facturas** emitidas y recibidas.
- **Extraer sus datos** (emisor, receptor, NIF, fecha, número, base imponible,
  tipo y cuota de IVA, retención de IRPF, total, concepto).
- **Clasificarlas a efectos de IVA**, incluidas:
  - operaciones sujetas y no exentas (tipos general, reducido y superreducido),
  - operaciones exentas,
  - operaciones no sujetas,
  - inversión del sujeto pasivo, en particular en servicios prestados por
    proveedores extranjeros.
- **Llevar los acumulados trimestrales y anuales** de IVA e IRPF.
- **Responder consultas** sobre los datos con información verificable: cada
  respuesta cita las facturas de las que sale.

Los datos se quedan en el equipo del usuario. La IA extrae e interpreta; los
cálculos los hace código determinista (ver `CLAUDE.md`).

## Etapas

### v1 — Facturas y resumen trimestral

- Subida de facturas emitidas y recibidas en PDF con texto, PDF escaneado o
  foto (JPG, PNG, HEIC). Facturae XML queda para más adelante.
- Extracción de datos con nivel de confianza (umbral inicial 0,90,
  configurable).
- Clasificación a efectos de IVA, con confirmación del usuario para lo dudoso.
- Resumen trimestral:
  - **Modelo 303** (IVA).
  - **Modelo 130** (pago fraccionado de IRPF), comprobando si el usuario está
    exento de presentarlo porque al menos el 70 % de sus ingresos del año
    anterior llevó retención (art. 109 del Reglamento del IRPF).
- Copia de seguridad local automática de la base de datos en
  `datos/copias/`.

### v2 — Consultas

- Consultas en lenguaje natural sobre los datos ("¿cuánto IVA soporté en
  software este año?"), con cita de las facturas y "no lo sé" cuando no haya
  datos.

### v3 — Anual y avisos

- Resúmenes anuales: **modelo 390** y ayuda para la **declaración de la renta**
  (rendimientos de actividades económicas).
- **Modelo 347** (operaciones con terceros).
- **Alertas de plazos** de presentación.

## Fuera de alcance (por ahora)

- Presentar modelos ante la AEAT.
- Contabilidad para sociedades.
- Uso multiusuario o en la nube.
