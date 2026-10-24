# Plantilla MADR

Plantilla usada en este trabajo, adaptada de **MADR** (*Markdown Architectural Decision Records*)
v4. Las secciones marcadas como obligatorias no se omiten; las opcionales se incluyen cuando
aportan.

```markdown
---
estado: propuesto | aceptado | reemplazado por ADR-nnnn | rechazado
fecha: AAAA-MM-DD
decisores: nombres de quienes decidieron
consultados: quienes aportaron conocimiento
informados: a quienes se comunica
iteracion: número de iteración de ADD
drivers: lista de identificadores (RF-xx, QA-xx, CON-xx, CRN-xx)
---

# ADR-nnnn: Título en forma de decisión, no de problema

## Contexto y planteo del problema

Qué fuerza esta decisión, en dos o tres párrafos. Si hay un número que la determina, va acá.

## Drivers de decisión

* Identificador y enunciado breve de cada driver que la decisión atiende

## Opciones consideradas

* Opción 1
* Opción 2
* Opción 3

## Resultado de la decisión

La opción elegida, y por qué. Una afirmación, no una divagación.

### Consecuencias

* **Bueno,** porque …
* **Malo,** porque …
* **Neutro,** porque …

### Confirmación

Cómo se va a verificar que la decisión está efectivamente implementada: una prueba, una revisión
de contrato, una medición. Sin esto, la decisión no es verificable y CON-04 no se cumple.

## Pros y contras de las opciones

### Opción 1

Descripción breve.

* Bueno, porque …
* Malo, porque …

## Más información

Enlaces a los drivers, a las vistas afectadas, a otros ADRs relacionados.
```

## Convenciones adoptadas

| Convención | Motivo |
|---|---|
| El título enuncia la **decisión**, no el problema («Despliegue activo-activo en tres regiones», no «Cómo desplegar») | Un índice de ADRs tiene que poder leerse como la lista de decisiones vigentes |
| El campo `drivers` del encabezado es obligatorio | Es lo que hace posible la [matriz de trazabilidad](../05-trazabilidad/matriz-drivers-decisiones.md) y QA-16 |
| La sección de confirmación es obligatoria | CON-04 exige que el prototipo sea verificablemente consistente con lo documentado |
| Se documentan **todas** las opciones consideradas, incluidas las obviamente malas, cuando descartarlas explícitamente aporta | Evita que alguien proponga en seis meses lo que ya se analizó y se rechazó |
| El idioma es español, y los nombres de elementos y eventos del sistema van en el idioma en que se codifican | Consistencia con el resto de la wiki, sin renombrar artefactos técnicos |
