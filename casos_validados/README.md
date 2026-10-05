# Casos validados

Casos de prueba fiscales (situación ficticia → resultado esperado) que
Gonzalo ha revisado y aprobado como correctos: clasificación de IVA,
modelos 303, 130, 390, 347...

Está vacía por ahora. Se va llenando a medida que el núcleo fiscal
implementa cada cálculo y Gonzalo valida el resultado con casos concretos.

## Regla

**Solo Gonzalo aprueba lo que entra aquí.** Un agente puede proponer un caso
nuevo (por ejemplo, en la PR que implementa el cálculo correspondiente), pero
no añadirlo a esta carpeta ni marcarlo como validado por su cuenta. Y, según
la línea roja de `criterio`, una vez un caso está aquí **nunca se modifica
sin su permiso explícito**, aunque parezca un simple ajuste.

## Cómo se usarán

Cada caso vivirá en su propio archivo (formato por decidir cuando se
implemente el primer cálculo: probablemente JSON o YAML con la entrada
ficticia y el resultado esperado). Los tests de `tests/` los cargarán y
compararán el resultado del código con el resultado aprobado.
