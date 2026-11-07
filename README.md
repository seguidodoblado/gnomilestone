<p align="right"><a href="README.en.md">🇺🇸 English</a></p>

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

Gestor de proyectos de escritorio para GNOME (GTK4/Adwaita), heredero espiritual de
GNOME Planner: proyectos, tareas y subtareas con diagrama de Gantt, lista de tareas,
tablero Kanban, gestión de recursos y uso, informes de avance, y sincronización
bidireccional opcional con GitHub Issues y GitHub Projects.

## Funcionalidades

- **Proyectos y tareas**: alta/baja de proyectos, tareas y subtareas con jerarquía,
  columna de tablero, fechas, duración, % completado, hitos, dependencias (con
  detección de ciclos) y asignación de personas.
- **Vistas de un proyecto** (rail de iconos al estilo Planner): Lista (listado plano
  con indentación, búsqueda y filtro por columna), Tablero Kanban (columnas
  configurables, tarjetas arrastrables), Gantt (barras con progreso, hitos, flechas
  de dependencia, arrastre para mover/redimensionar, zoom y propagación en cascada a
  hijas y dependientes), Recursos (alta/edición, avatar, carga por persona) y Uso de
  recursos (ocupación en el tiempo, con sobrecarga marcada en rojo).
- **Gantt global**: superpone los proyectos elegidos en un único diagrama para
  detectar solapes entre ellos.
- **Informes**: panel visual por proyecto con progreso global, tareas por estado,
  avance (sin empezar/en curso/completadas) y alertas de fechas (vencidas,
  planificadas pasadas, próximas 7 días, recursos activos).
- **Vencimientos**: el nombre de una tarea se pinta en naranja si ya pasó su final
  planificado y en rojo si ya pasó su fecha límite; filtro para ocultar las tareas
  completadas.
- **Integración con GitHub**: vinculación opcional de un proyecto a un repositorio
  (y a un GitHub Project), con sincronización bidireccional de Issues (traer y crear
  tareas, enviar cambios de estado) y de los campos del Project.
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

Requiere Python 3.11+, PyGObject y GTK4 del sistema.

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
