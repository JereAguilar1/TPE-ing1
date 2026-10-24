# 1.5 Restricciones

Las restricciones son decisiones ya tomadas que el diseño no puede cambiar. En ADD se tratan
distinto de los requisitos: no se negocian ni se priorizan, se satisfacen. Lo que sí se documenta
es **cómo** el diseño las absorbe y qué libertad le quitan.

| ID | Restricción | Tipo | Origen | Impacto en el diseño |
|---|---|---|---|---|
| **CON-01** | El proceso de diseño debe seguir el método ADD, con un mínimo de 4 iteraciones, capturando los artefactos intermedios y finales | Proceso | Enunciado §4 | Determina la estructura entera de esta wiki y el [plan de iteraciones](../00-gestion/plan-de-iteraciones.md) |
| **CON-02** | Las decisiones de diseño deben documentarse exhaustivamente como ADRs en formato MADR | Proceso | Enunciado §4 | Los ADRs son el registro normativo; las vistas y esta wiki son derivados de ellos ([plantilla](../03-adr/plantilla-madr.md)) |
| **CON-03** | La documentación debe mantenerse en formato wiki, con actualizaciones periódicas que muestren la evolución del trabajo y la labor de cada integrante | Proceso | Enunciado §4 | Obliga a commits incrementales y atribuidos; ver [convenciones de trabajo](../00-gestion/equipo.md#convenciones-de-trabajo) y [bitácora](../00-gestion/bitacora.md) |
| **CON-04** | Debe adoptarse *Spec-driven development*: el código del prototipo tiene que ser trazable y consistente con la arquitectura documentada y respetar las especificaciones definidas contractualmente | Proceso / Técnica | Enunciado §4 y §5 | Es el fundamento de [ADR-0009](../03-adr/ADR-0009-contratos-spec-driven.md): los contratos son artefactos de primera clase, no documentación generada a posteriori |
| **CON-05** | El alcance del prototipo debe acotarse para ser viable dentro del cronograma | Proceso | Enunciado §2 | Fuerza a diseñar la arquitectura completa pero a construir solo los caminos que demuestran los escenarios más riesgosos |
| **CON-06** | Al menos uno de los módulos avanzados (Opción A — recomendación, u Opción B — asistente virtual) debe incorporarse en la 2da entrega | Alcance | Enunciado, *Requerimientos Avanzados* | La arquitectura de esta entrega debe exponer un punto de extensión capaz de alojar cualquiera de los dos sin cambios estructurales |
| **CON-07** | La integración con sistemas de viajes e interfaces de agencias de terceros debe hacerse a través de APIs estándar del dominio | Técnica | Enunciado, *Requerimientos Funcionales* | Descarta el raspado de pantalla y los acuerdos de integración ad-hoc; el modelo canónico debe poder recibir NDC, OTA/HTNG y equivalentes ([ADR-0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md)) |
| **CON-08** | El acceso al correo del usuario requiere su autorización explícita, y el acceso debe ser seguro | Técnica / Legal | Enunciado, *Atributos de Calidad — Seguridad* | Descarta pedirle al usuario su contraseña de correo; obliga a autorización delegada ([ADR-0007](../03-adr/ADR-0007-identidad-y-comparticion.md)) |
| **CON-09** | El equipo es de 4 integrantes con dedicación parcial, en el marco de una materia | Organizacional | Modalidad del curso | Limita el número de elementos que el equipo puede diseñar *y* construir; es el argumento contra una granularidad fina de servicios en [ADR-0001](../03-adr/ADR-0001-estilo-arquitectonico.md) |
| **CON-10** | El sistema es de uso global y procesa información personal, por lo que debe cumplir el marco normativo de datos personales de cada región donde opera | Legal | Enunciado, *Atributos de Calidad — Seguridad y Usabilidad* | Obliga a contemplar residencia de datos por región y derechos de acceso y supresión (QA-14, QA-18). Marcos aplicables identificados: Reglamento (UE) 2016/679 (GDPR) para la Unión Europea y Ley 25.326 de Protección de los Datos Personales para Argentina |

## Restricciones autoimpuestas

Estas no vienen del enunciado: las adopta el equipo para acotar el espacio de diseño y hacer el
trabajo viable dentro de CON-05 y CON-09. Se registran como restricciones —y no como decisiones—
porque una vez adoptadas el resto del diseño las da por dadas.

| ID | Restricción autoimpuesta | Motivo |
|---|---|---|
| **CON-A1** | El sistema no implementa un motor de reservas propio: lee y refleja reservas hechas en otros sistemas | Mantener el alcance en lo que el enunciado efectivamente pide (ver [1.1 Alcance](01-proposito-y-alcance.md#fuera-del-alcance)) |
| **CON-A2** | Se asume despliegue sobre una nube pública con al menos tres regiones y servicios gestionados de mensajería, almacenamiento y análisis | Alcanzar 5 minutos de inactividad al mes con un equipo de 4 personas es inviable sobre infraestructura propia |
| **CON-A3** | Se diseñan los adaptadores de trenes y autobuses como puntos de extensión, pero no se especifican sus proveedores concretos | El enunciado los pide como «integración futura», y no hay un estándar único del dominio comparable a NDC |
| **CON-A4** | El número de servicios del plano operacional se mantiene por debajo de 15 | Por encima de ese número el costo de operación y de documentación excede lo que 4 personas con dedicación parcial pueden sostener (CON-09) |
