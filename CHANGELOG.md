# Changelog

Todos los cambios relevantes de este proyecto se documentarán
en este archivo.

## [Unreleased]

### Added

- Estructura inicial del proyecto: paquete `gnomilestone` (app, settings, theme, i18n, ui) y tests básicos
- Ventana principal con menú de cabecera ("Preferencias", "Acerca de GnoMilestone") y estado vacío a la espera de la gestión de proyectos; el panel lateral de proyectos se puede colapsar desde un botón en la cabecera
- Preferencias de idioma y tema: selector Sistema/Español/English y Sistema/Claro/Oscuro, persistidos en `~/.config/gnomilestone/settings.json` y aplicados reiniciando la app
- Traducción al inglés (i18n con `gettext`): catálogo `po/en.po`, scripts `i18n-extract.sh`/`i18n-compile.sh` y compilación automática al empaquetar
- Empaquetado `.deb` (`build-deb.sh`, `debian/`) con icono de la app, páginas de manual en inglés y español, y `.deb` que pasa lintian sin errores
- Integración continua (`ci.yml`: ruff, pytest y `.deb` con lintian) y despliegue (`cd.yml`: al subir una etiqueta `vX.Y.Z` ejecuta el CI sobre ese commit y, solo si pasa, deja la release en borrador con el mismo `.deb` que construyó el CI)
- Modelo de datos SQLite (`store.py`, `models.py`): proyectos, tareas y subtareas, dependencias (con detección de ciclos), columnas de tablero y recursos/asignaciones
- Gestión de proyectos: lista de proyectos con alta/baja, listado de tareas por proyecto, alta/edición de tareas (jerarquía, columna, fechas, duración, % completado, hitos, dependencias y asignación de personas), columnas del tablero configurables (alta/renombrado/orden/borrado con migración de tareas) y pantalla de recursos (carga por persona; el alta normal es al asignar en la tarea, con alta manual secundaria)
- Asignación de recursos desde el diálogo de tarea: autocompletado, creación al asignar si el nombre no existía, y vista de Recursos con inicial/color, email y número de tareas
- Avatar de recurso editable (color o imagen local; campo `avatar_url` preparado para el avatar de GitHub al vincular), dibujado en círculo y visible en Recursos, diálogo de tarea, columna «Asignado» de Lista/Gantt y tarjetas del Tablero
- Selector de fecha real (calendario con botones "Hoy"/"Sin fecha", formato DD/MM/AAAA) en vez de texto libre; listado de tareas con líneas conectoras de jerarquía (estilo `tree`)
- Vista Gantt (`ganttcalc.py`, `task_tree_view.py`, `gantt_drawing_area.py`, `gantt_view.py`): árbol de tareas sincronizado en scroll con las barras (con relleno de progreso), hitos y flechas de dependencia, con zoom; disponible por proyecto y en una vista global (`global_gantt_view.py`) que superpone los proyectos elegidos con checks para detectar solapes. El reparto entre el árbol y el lienzo es un divisor arrastrable (`Gtk.Paned`) y cada columna del árbol se puede redimensionar por separado
- Doble clic para editar una tarea y menú contextual (botón derecho: Editar tarea/Eliminar tarea) tanto en la Tabla como en el árbol y las propias barras del Gantt, por proyecto y en la vista global
- Interacción completa del Gantt: arrastrar una barra mueve su fecha de inicio, arrastrar su borde derecho cambia la duración (con vista previa en vivo y cursor `grab`/`col-resize` según dónde se pase por encima), siempre encajado al día
- Jerarquía padre/hija en el Gantt: al mover una tarea con subtareas, estas la siguen (mismo desplazamiento, a cualquier profundidad); al redimensionarla, las descendientes que ya no quepan se recortan en cascada a su nuevo rango; una subtarea arrastrada directamente nunca puede salirse del rango de su tarea padre
- Dependencias: al mover o redimensionar una tarea, sus dependientes se desplazan en cascada (en vivo durante el arrastre) para no solaparse con ella
- Línea vertical del día actual en el Gantt (regla de fechas y lienzo) y zoom con Ctrl+rueda del ratón, además de los botones
- Lenguaje visual propio para el Gantt: las tareas resumen (con subtareas) se dibujan como una píldora fina en vez de una barra normal, las barras de tareas hoja llevan las esquinas redondeadas, y las flechas de dependencia se trazan como una curva suave (bézier) en vez de en ángulo recto o en diagonal
- Vistas Lista (`table_view.py`: listado plano con indentación de jerarquía, búsqueda por texto y filtro por columna del tablero), Tablero (`kanban_view.py`: una columna por cada columna del tablero, distinguidas por un color propio, con tarjetas arrastrables entre ellas), Gantt, Recursos (`resource_dialog.py` como vista embebida) y Uso de recursos (`resource_usage.py` / `resource_usage_view.py`: ocupación en el tiempo por persona, con días en sobrecarga —más del 100 % de dedicación— marcados en rojo; si la persona ya está en un ancestro, la hija no vuelve a sumar), accesibles desde un rail de iconos vertical al estilo Planner (`project_detail_view.py`), que también centraliza la creación/edición/borrado de tareas y la propagación de jerarquía/dependencias al arrastrar en el Gantt. Los ajustes de las columnas del Tablero viven en un botón con rueda dentada dentro de esa misma vista, no en la barra de herramientas común
- Tareas vencidas en Lista, árbol del Gantt y Tablero (`ganttcalc.estado_vencimiento`, `ui/vencimiento.py`): el nombre se pinta en naranja cuando ya pasó su final planificado y en rojo cuando ya pasó su fecha límite. Las tareas completadas y las que no tienen fechas no se marcan; el tooltip explica el aviso
- Filtro «Mostrar completadas» en la barra del proyecto y en el Gantt global: al desmarcarlo se ocultan las tareas al 100 % en Lista, Tablero y Gantt. Una tarea resumen solo se oculta si toda su rama está completada, para no dejar subtareas pendientes huérfanas; Recursos y Uso no se ven afectados
- Fecha límite visible en el Gantt: una línea discontinua de holgura une el final de la barra con la fecha límite, rematada por una bandera cuyo color sigue la urgencia (rojo si está vencida, naranja si ya pasó el plan, atenuado si aún hay margen); el tooltip indica la fecha y los días de margen (o si el plan ya la supera)

### Changed

- Se centraliza en `project_detail_view.py` la lógica de un proyecto (antes repartida en `window.py`), simplificando la ventana principal; `ordenar_jerarquicamente` (prefijos de conector para listados planos) pasa de `window.py` a `task_tree_view.py`, de donde ya la puede reutilizar la vista Tabla

### Fixed

- El estado vacío "Selecciona o crea un proyecto" no aparecía centrado hasta maximizar la ventana: `Gtk.Stack` mide su tamaño por defecto como el máximo entre **todas** sus páginas (aunque no estén visibles), así que la página ancha del Gantt desplazaba el centrado de la página vacía. Se fija `hhomogeneous`/`vhomogeneous` a `False` en los `Gtk.Stack` del panel de detalle y del selector Tabla/Gantt.
- El menú contextual (botón derecho) en las tareas siempre aparecía en la misma posición en vez de donde se pulsaba, y a veces no llegaba a mostrarse: `Gdk.Rectangle(x=..., y=..., width=..., height=...)` ignora en silencio los argumentos del constructor en esta versión de PyGObject; había que fijar sus atributos tras crearlo.
- Mover/redimensionar una barra más allá del borde visible del Gantt la sacaba del área dibujable (el lienzo solo recalculaba su tamaño con los datos guardados, no con la posición en vivo del arrastre); ahora crece dinámicamente por ambos lados durante el arrastre, compensando el scroll para que la vista no salte
- El final planificado (`fecha_fin_planificada`) se quedaba desfasado al mover o redimensionar una tarea en el Gantt y al propagar el cambio a hijas y dependientes: ahora se recalcula como inicio + duración - 1 en todos esos caminos. El pull de GitHub también contaba la duración sin el día final y no rellenaba el final planificado, lo que podía adelantar la fecha objetivo en cada sincronización
- Redimensionar una tarea con nietas (hija de hija) no las recortaba si ya no cabían, solo a las hijas directas; `limitar_hijos_tras_redimensionar` ahora recorta en cascada a cualquier profundidad
- Las filas del árbol de tareas no tenían la misma altura que las barras del Gantt (el tema añade su propio relleno vertical por encima de los 32px fijados), desalineando ambos; se anula ese relleno por CSS
- Un hito se podía guardar sin fecha, quedando invisible en el Gantt sin ningún aviso (no hay dónde situar un punto en el tiempo sin fecha); el diálogo de tarea ahora la exige cuando "Es un hito" está marcado
