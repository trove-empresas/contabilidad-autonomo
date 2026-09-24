# CLAUDE.md — contabilidad-autonomo

## Reglas generales

Las reglas generales de trabajo están en el `CLAUDE.md` del repositorio
[`trove-empresas/criterio`](https://github.com/trove-empresas/criterio).
**Esas reglas prevalecen** sobre lo que diga este archivo. Si hay conflicto,
se sigue `criterio` y se señala la contradicción para corregirla aquí.

Este archivo solo añade los principios propios de esta app.

## Qué es esta app

App local para que un autónomo en España gestione sus facturas, su IVA y su
IRPF. Visión y etapas en [`docs/producto.md`](docs/producto.md). Decisiones
registradas en [`docs/decisiones.md`](docs/decisiones.md). Opciones de
tecnología en [`docs/propuesta-tecnica.md`](docs/propuesta-tecnica.md)
(la elección final es de Gonzalo; no se implementa ninguna hasta que decida).

## Principios de la app

1. **La IA solo extrae e interpreta; el código calcula.**
   La IA se limita a extraer datos de las facturas y a interpretar las
   preguntas del usuario. Todos los cálculos (bases, cuotas, acumulados,
   modelos 303, 130, 390, 347, etc.) los hace código determinista y cubierto
   por pruebas. Nunca se pide a un modelo que sume, reparta o calcule un
   importe.

2. **Toda factura lleva nivel de confianza; lo dudoso lo confirma el usuario.**
   Cada factura procesada guarda un nivel de confianza de la extracción y de
   la clasificación. Lo que no alcance el umbral queda pendiente y **no entra
   en ningún cálculo** hasta que el usuario lo confirme o corrija.

3. **Las respuestas citan sus fuentes; sin datos, "no lo sé".**
   Toda respuesta a una consulta indica las facturas de las que sale.
   Si no hay datos suficientes para responder, la respuesta es "no lo sé".
   No se rellenan huecos con suposiciones.

4. **Las reglas fiscales llevan referencia normativa y fecha.**
   Cada regla fiscal del código (tipos, exenciones, inversión del sujeto
   pasivo, límites, plazos…) indica la norma y el artículo en que se basa y la
   fecha desde la que aplica (y hasta cuándo, si se conoce). Una regla sin
   referencia no se da por buena.

5. **Los datos reales nunca entran en el repositorio.**
   Facturas, bases de datos locales, exportaciones y credenciales se quedan
   fuera (ver `.gitignore`). Las pruebas usan exclusivamente facturas
   ficticias, con NIF y datos inventados.
