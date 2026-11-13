<p align="center">
  <img src="src/gnomilestone/assets/gnomilestone.svg" alt="Logotipo de GnoMilestone" width="128">
</p>

<h1 align="center">GnoMilestone</h1>

<p align="center">
  <a href="https://github.com/seguidodoblado/gnomilestone/releases"><img alt="release" src="https://img.shields.io/github/v/release/seguidodoblado/gnomilestone"></a>
  <a href="https://github.com/seguidodoblado/gnomilestone/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/seguidodoblado/gnomilestone/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/seguidodoblado/gnomilestone/actions/workflows/cd.yml"><img alt="CD" src="https://github.com/seguidodoblado/gnomilestone/actions/workflows/cd.yml/badge.svg"></a>
  <a href="https://github.com/seguidodoblado/gnomilestone/blob/main/COPYING"><img alt="license" src="https://img.shields.io/github/license/seguidodoblado/gnomilestone"></a>
  <a href="https://github.com/seguidodoblado/gnomilestone/commits/main/"><img alt="last commit" src="https://img.shields.io/github/last-commit/seguidodoblado/gnomilestone"></a>
  <a href="https://github.com/seguidodoblado/gnomilestone/commits/main/"><img alt="total commits" src="https://img.shields.io/github/commit-activity/t/seguidodoblado/gnomilestone"></a>
  <a href="https://github.com/seguidodoblado/gnomilestone/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/seguidodoblado/gnomilestone?style=flat"></a>
  <a href="https://github.com/seguidodoblado/gnomilestone/issues"><img alt="issues" src="https://img.shields.io/github/issues/seguidodoblado/gnomilestone"></a>
  <a href="https://github.com/seguidodoblado/gnomilestone"><img alt="language" src="https://img.shields.io/github/languages/top/seguidodoblado/gnomilestone"></a>
  <a href="https://codetime.dev"><img alt="CodeTime Badge" src="https://shields.jannchie.com/endpoint?style=flat&color=0284c7&url=https%3A%2F%2Fcodetime.dev%2Fv3%2Fusers%2Fshield%3Fuid%3D36830"></a>
  <a href="https://wakatime.com/badge/github/seguidodoblado/gnomilestone"><img src="https://wakatime.com/badge/github/seguidodoblado/gnomilestone.svg" alt="wakatime"></a>
</p>

---

## 🇪🇸 Español

Gestor de proyectos de escritorio para GNOME (GTK4/Adwaita), heredero espiritual de
GNOME Planner: proyectos, tareas y subtareas con diagrama de Gantt, lista de tareas,
tablero Kanban, gestión de recursos y uso, informes de avance, y sincronización
bidireccional opcional con GitHub Issues y GitHub Projects, y documentación propia de cada
proyecto (notas, diagramas y líneas de tiempo).

## Funcionalidades

- **Proyectos y tareas**: alta/baja de proyectos, tareas y subtareas con jerarquía,
  columna de tablero, fechas, duración, % completado, tipo (trabajo, error o
  funcionalidad), el hito al que contribuyen, dependencias (con detección de ciclos),
  asignación de personas con su dedicación, prioridad (hasta «Urgente»), etiquetas de
  colores y comentarios.
- **Hitos**: puntos de control con fecha objetivo ligados a los Milestones de GitHub, con
  su avance calculado desde las tareas que contribuyen a ellos; se ven en el Gantt (rombo y
  línea de meta), en Blueprint y en el Roadmap.
- **Diálogo de tarea**: ventana con pestañas (General, Fechas y progreso, Asignaciones,
  Dependencias y Comentarios), descripción en Markdown con barra de formato y vista
  previa, selectores con búsqueda para la tarea padre y las dependencias, calendario con
  atajos (Hoy, Mañana, Próxima semana), validación campo a campo y aviso de cambios sin
  guardar.
- **Vistas de un proyecto** (rail de iconos al estilo Planner): Lista (listado plano
  con indentación y tareas padre plegables, búsqueda y filtro por columna, con columnas
  de prioridad, tipo y etiquetas), Tablero Kanban (columnas configurables, tarjetas
  arrastrables, subtareas como cápsulas con su progreso), Gantt
  (barras con progreso, hitos, flechas de dependencia, arrastre para mover/redimensionar,
  zoom y propagación en cascada a hijas y dependientes), Recursos (tarjetas de visita
  de las personas, con sus equipos, medios y lugares) y Uso de recursos (ocupación en el
  tiempo de las personas, con sobrecarga marcada en rojo).
- **Recursos**: cada persona es una tarjeta de visita con su cargo, email y teléfono y
  tres tablas editables (equipos con su hardware, medios con licencias y accesos, y
  lugares de trabajo con su dirección), plegables y con el contorno del color de su
  avatar; el nombre, el email público y el avatar se pueden traer de GitHub.
- **Gantt global**: superpone los proyectos elegidos en un único diagrama para
  detectar solapes entre ellos.
- **Informes**: panel visual por proyecto en cinco pestañas: Resumen (estado general y
  riesgo temporal), Flujo de trabajo (tareas por estado, ritmo de trabajo, tiempo medio
  y acumulación por columna), Planificación (burndown/burnup, desviación, fechas
  planificadas frente a reales y ruta crítica), Equipo (reparto, trabajo por tipo y
  resultados y riesgo por persona) y Auditoría.
- **Usuarios y auditoría**: cada cambio de una tarea queda firmado con el usuario de
  gestión activo; la pestaña Auditoría muestra los cambios por usuario y el registro
  cronológico.
- **Documentación del proyecto**: ficha propia de cada proyecto, con contenido de la
  app (sin leer ficheros externos), organizada en Visión general (con el contexto del proyecto traído de su repositorio de
  GitHub), Arquitectura, Especificaciones, Blueprint y Decisiones técnicas. Las notas son tarjetas con Markdown (plantillas,
  estado, subpáginas, enlaces internos `[[Título]]` y `#27`, bloques de código con
  coloreado y diagramas Mermaid de flujo), se editan en una ventana aparte y guardan
  sus versiones anteriores; las subsecciones de diagramas tienen un editor de nodos y
  flechas; y Blueprint dibuja Historial, Hitos y Roadmap a partir de las tareas, con
  zoom. Hay árbol de navegación plegable y búsqueda.
- **Vencimientos**: el nombre de una tarea se pinta en naranja si ya pasó su final
  planificado y en rojo si ya pasó su fecha límite, y la fecha límite se señala con una
  bandera en el Gantt y en Uso; las tareas completadas se ven por defecto, con un filtro
  para ocultarlas.
- **Columna de completadas y archivo**: una columna del tablero se puede marcar como «de
  completadas» (entrar en ella pone la tarea al 100 % y salir lo deshace), y las tareas
  que ya no interesan se pueden archivar —incluso todas las completadas de golpe— y
  recuperar después desde una lista de archivadas.
- **Integración con GitHub**: vinculación opcional de un proyecto a un repositorio
  (y a un GitHub Project), con sincronización bidireccional de Issues (traer y crear
  tareas, enviar cambios de estado), de los campos del Project (incluidas las columnas
  del tablero y la prioridad), de las etiquetas y de los comentarios; eliminar una tarea
  borra también su issue.
- **Preferencias**: selector de idioma (Sistema/Español/English) y de tema
  (Sistema/Claro/Oscuro), persistidos en `~/.config/gnomilestone/settings.json`.

## Instalación

Desde el `.deb` generado por `./build-deb.sh` (requiere `dpkg-dev`):

```sh
./build-deb.sh
sudo dpkg -i ../gnomilestone_*.deb
```

## Uso

```sh
gnomilestone
```

## Desarrollo

Requiere Python 3.11+, PyGObject y GTK4 del sistema, más Pygments (`python3-pygments`,
opcional: sin él los bloques de código no se colorean).

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check .
.venv/bin/pytest -q
sh i18n-compile.sh   # genera los catálogos .mo antes de ejecutar la app o los tests de i18n
python3 -m gnomilestone.app
```

## Licencia

Este proyecto se distribuye bajo la GNU General Public License, versión 3 o posterior
(ver `COPYING`).

---

## 🇺🇸 English

Desktop project manager for GNOME (GTK4/Adwaita), the spiritual successor to GNOME
Planner: projects, tasks and subtasks with a Gantt chart, task list, Kanban board,
resource and usage management, progress reports, and optional two-way synchronization
with GitHub Issues and GitHub Projects, and each project's own documentation (notes,
diagrams and timelines).

## Features

- **Projects and tasks**: create/delete projects, tasks and subtasks with hierarchy,
  board column, dates, duration, % complete, type (work, bug or feature), the
  milestone they contribute to, dependencies (with cycle detection), people assignment
  with their dedication, priority (up to “Urgent”), colored labels and comments.
- **Milestones**: checkpoints with a target date tied to GitHub Milestones, with their
  progress computed from the tasks that contribute to them; they show in the Gantt
  (diamond and goal line), in Blueprint and in the Roadmap.
- **Task dialog**: a tabbed window (General, Dates and progress, Assignments,
  Dependencies and Comments), a Markdown description with a formatting bar and preview,
  searchable pickers for the parent task and dependencies, a calendar with shortcuts
  (Today, Tomorrow, Next week), field-by-field validation and a warning about unsaved
  changes.
- **Views within a project** (Planner-style icon rail): List (flat listing with
  hierarchy indentation and foldable parent tasks, text search and board-column filter,
  with priority, type and label columns), Kanban board (configurable columns, draggable
  cards, subtasks as capsules showing their progress), Gantt (bars with
  progress fill, milestones, dependency arrows, drag to move/resize, zoom and cascading
  propagation to children and dependents), Resources (business cards of the
  people, with their equipment, media and places) and Resource usage (people's occupancy
  over time, with overload marked in red).
- **Resources**: each person is a business card with their role, email and phone and
  three editable tables (equipment with its hardware data, media with licenses and
  access, and workplaces with their address), foldable and outlined in the color of
  their avatar; the name, public email and avatar can be fetched from GitHub.
- **Global Gantt**: overlays the chosen projects on a single chart to spot overlaps
  between them.
- **Reports**: a visual panel per project in five tabs: Summary (general status and time
  risk), Workflow (tasks per status, work rhythm, average time and accumulation per
  column), Planning (burndown/burnup, deviation, planned versus actual dates and
  critical path), Team (distribution, work by type and results and risk per person) and
  Audit.
- **Users and audit**: every change to a task is signed with the active management user;
  the Audit tab shows the changes per user and the chronological log.
- **Project documentation**: each project's own documentation, with content stored in
  the app (no external files read), organized in Overview (with the project context pulled from its GitHub repository),
  Architecture, Specifications, Blueprint and Technical decisions. Notes are Markdown cards (templates, status,
  subpages, internal links `[[Title]]` and `#27`, highlighted code blocks and Mermaid
  flowcharts), edited in a separate window, and they keep their earlier versions;
  diagram subsections have a node-and-arrow editor; and Blueprint draws History,
  Milestones and Roadmap from the tasks, with zoom. There is a collapsible navigation
  tree and a search.
- **Due dates**: a task's name is shown in orange once it is past its planned end,
  and in red once it is past its deadline, and the deadline is marked with a flag in the
  Gantt and in Usage; completed tasks are shown by default, with a filter to hide them.
- **Completed column and archive**: a board column can be marked as the “completed” one
  (entering it sets the task to 100% and leaving it undoes that), and tasks that no
  longer matter can be archived —including all the completed ones at once— and
  recovered later from a list of archived tasks.
- **GitHub integration**: optionally link a project to a repository (and a GitHub
  Project), with two-way synchronization of Issues (pull and create tasks, push
  status changes), of the Project's fields (including the board columns and the
  priority), of labels and of comments; deleting a task also deletes its issue.
- **Preferences**: language selector (System/Español/English) and theme selector
  (System/Light/Dark), persisted in `~/.config/gnomilestone/settings.json`.

## Installation

From the `.deb` built by `./build-deb.sh` (requires `dpkg-dev`):

```sh
./build-deb.sh
sudo dpkg -i ../gnomilestone_*.deb
```

## Usage

```sh
gnomilestone
```

## Development

Requires Python 3.11+, PyGObject and the system's GTK4, plus Pygments (`python3-pygments`,
optional: without it, code blocks are not highlighted).

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check .
.venv/bin/pytest -q
sh i18n-compile.sh   # builds the .mo catalogs before running the app or the i18n tests
python3 -m gnomilestone.app
```

## License

This project is distributed under the GNU General Public License, version 3 or later
(see `COPYING`).
