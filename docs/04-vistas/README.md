# 4. Vistas arquitectónicas

Una arquitectura no se documenta con un diagrama: se documenta con un conjunto de vistas, cada una
mostrando un tipo de estructura distinto y respondiendo preguntas distintas. El enunciado lo pide
explícitamente (§4: «deben crearse las vistas arquitectónicas adecuadas […] que reflejen las
estructuras del sistema»).

## Las vistas de esta entrega

| Vista | Tipo de estructura | Responde |
|---|---|---|
| [Contexto](vista-contexto.md) | — (el sistema como caja negra) | ¿Dónde empieza y termina el sistema? ¿Con quién habla? |
| [Módulos — nivel 1](vista-modulos-nivel-1.md) | **Estática**: unidades de implementación | ¿Cómo se divide el código? ¿Qué puede depender de qué? |
| [Módulos — nivel 2 (adaptadores, identidad y extensión)](vista-modulos-adaptadores.md) | **Estática refinada**: complementos versionados, `identity-access`, `sharing`, `locales-icu` y punto de extensión | ¿Por qué agregar un proveedor (`QA-10`), transporte (`QA-15`), región (`QA-18`) o el módulo avanzado (`CON-06`) no toca el dominio? |
| [Componentes y conectores — nivel 1](vista-cyc-nivel-1.md) | **Dinámica**: elementos en ejecución | ¿Qué corre en tiempo de ejecución y cómo se comunica? |
| [Despliegue — nivel 1](vista-despliegue-nivel-1.md) | **De asignación**: software sobre hardware | ¿Dónde corre cada cosa a escala global? |
| [Despliegue — nivel 2](vista-despliegue-nivel-2.md) | **De asignación refinada**: interior regional, plano de datos y elasticidad | ¿Cómo se despliega en 3 AZs, cómo cierra `R-1`/`R-4`, cuántas réplicas corren y cómo escala? |
| [Seguridad, privacidad y residencia de datos](vista-seguridad-y-datos.md) | **Transversal híbrida** (C&C + asignación de datos y claves) | ¿Dónde están las fronteras de confianza, cómo se protegen 9 M de buzones (`QA-13`), cómo cierra `R-6` y cómo se suprime PII en ambos planos (`QA-14`)? |

Las estructuras son distintas y no se pueden mezclar arbitrariamente en un dibujo. Un módulo no es
un componente: `provider-sync` es **un** módulo con varios adaptadores dentro, y en ejecución es
**varias** instancias replicadas en tres regiones.

## Reglas de consistencia entre vistas

Estas reglas se verifican al cerrar cada iteración (auditoría final registrada en
[iteración 4, paso 7](../02-proceso-add/iteracion-4/paso-7-analisis.md#verificación-de-consistencia-entre-vistas-criterio-de-salida-6)).
Si alguna se viola, hay un error de diseño, no un error de dibujo.

1. Todo módulo de la vista de módulos tiene al menos un componente que lo realiza en la vista C&C.
2. Todo componente de la vista C&C tiene un destino de despliegue en la vista de despliegue.
3. Toda dependencia de la vista de módulos corresponde a un conector de la vista C&C o es interna
   a un componente.
4. Toda interfaz externa del diagrama de contexto (E-01…E-16) tiene un componente responsable de
   atenderla.
5. Toda interfaz entre componentes tiene un contrato declarado y regla de evolución
   ([ADR-0009](../03-adr/ADR-0009-contratos-spec-driven.md), [ADR-0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md)).

## Nivel de detalle

Las vistas de **nivel 1** muestran la primera descomposición del sistema producida en la iteración 1
de ADD. Las vistas y recorridos de **nivel 2** detallan el interior de los módulos (iteraciones 2 y
4), el dimensionamiento, la topología de datos multirregión y el autoescalado de la infraestructura
(iteración 3) y la arquitectura transversal de seguridad, privacidad y residencia de datos
(iteración 4).

| Vista | Nivel 1 (iteración 1) | Nivel 2 / Refinamiento (iteraciones 2 a 4) |
|---|---|---|
| Módulos | Subsistemas y dependencias ([nivel 1](vista-modulos-nivel-1.md)) | Interior de `itinerary` ([iteración 2 §5](../02-proceso-add/iteracion-2/README.md#paso-5--instanciar-elementos-asignar-responsabilidades-y-definir-interfaces)) y subsistema de adaptadores, `identity-access`, `sharing`, `locales-icu` y extensión ([nivel 2](vista-modulos-adaptadores.md)) |
| C&C | Componentes y tipos de conector ([nivel 1](vista-cyc-nivel-1.md)) | Secuencias de los casos de uso UC-1…UC-7 ([iteración 2, paso 7](../02-proceso-add/iteracion-2/paso-7-analisis.md)) y secuencia de supresión en dos planos ([seguridad y datos §5](vista-seguridad-y-datos.md#5-secuencia-de-supresión-verificable-en-ambos-planos--30-días--adr-0030)) |
| Despliegue y datos | Tres regiones y asignación gruesa ([nivel 1](vista-despliegue-nivel-1.md)) | Dimensionamiento, autoescalado y plano de datos ([nivel 2](vista-despliegue-nivel-2.md)) + fronteras de confianza, claves y residencia normativa ([seguridad y datos](vista-seguridad-y-datos.md)) |
