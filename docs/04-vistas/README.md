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
| [Componentes y conectores — nivel 1](vista-cyc-nivel-1.md) | **Dinámica**: elementos en ejecución | ¿Qué corre en tiempo de ejecución y cómo se comunica? |
| [Despliegue — nivel 1](vista-despliegue-nivel-1.md) | **De asignación**: software sobre hardware | ¿Dónde corre cada cosa a escala global? |
| [Despliegue — nivel 2](vista-despliegue-nivel-2.md) | **De asignación refinada**: interior regional, plano de datos y elasticidad | ¿Cómo se despliega en 3 AZs, cómo cierra `R-1`/`R-4`, cuántas réplicas corren y cómo escala? |

Las tres estructuras son distintas y no se pueden mezclar en un dibujo. Un módulo no es un
componente: `provider-sync` es **un** módulo con varios adaptadores dentro, y en ejecución es
**varias** instancias replicadas en tres regiones.

## Reglas de consistencia entre vistas

Estas reglas se verifican al cerrar cada iteración. Si alguna se viola, hay un error de diseño, no
un error de dibujo.

1. Todo módulo de la vista de módulos tiene al menos un componente que lo realiza en la vista C&C.
2. Todo componente de la vista C&C tiene un destino de despliegue en la vista de despliegue.
3. Toda dependencia de la vista de módulos corresponde a un conector de la vista C&C o es interna
   a un componente.
4. Toda interfaz externa del diagrama de contexto (E-01…E-16) tiene un componente responsable de
   atenderla.
5. Toda interfaz entre componentes tiene un contrato declarado
   ([ADR-0009](../03-adr/ADR-0009-contratos-spec-driven.md)).

## Nivel de detalle

Las vistas de **nivel 1** muestran la primera descomposición del sistema producida en la iteración 1
de ADD. Las vistas y recorridos de **nivel 2** detallan el interior de los módulos (iteración 2) y el
dimensionamiento, la topología de datos multirregión y el autoescalado de la infraestructura
([vista de despliegue — nivel 2](vista-despliegue-nivel-2.md), iteración 3).

| Vista | Nivel 1 (iteración 1) | Nivel 2 (iteraciones 2-3) |
|---|---|---|
| Módulos | Subsistemas y dependencias | Interior de `itinerary`, `booking-extraction` y la capa de adaptadores ([iteración 2 §5](../02-proceso-add/iteracion-2/README.md#paso-5--instanciar-elementos-asignar-responsabilidades-y-definir-interfaces)) |
| C&C | Componentes y tipos de conector | Secuencias de los casos de uso UC-1…UC-7 ([iteración 2, paso 7](../02-proceso-add/iteracion-2/paso-7-analisis.md)) |
| Despliegue | Tres regiones y asignación gruesa ([nivel 1](vista-despliegue-nivel-1.md)) | Dimensionamiento, autoescalado y topología del plano de datos ([nivel 2](vista-despliegue-nivel-2.md)) |
