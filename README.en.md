<p align="right"><a href="README.md">🇪🇸 Español</a></p>

<p align="center">
  <img src="src/gnomilestone/assets/gnomilestone.svg" alt="GnoMilestone logo" width="128">
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

Desktop project manager for GNOME (GTK4/Adwaita), the spiritual successor to GNOME
Planner: projects, tasks and subtasks with a Gantt chart, task list, Kanban board,
resource and usage management, progress reports, and optional two-way synchronization
with GitHub Issues and GitHub Projects.

## Features

- **Projects and tasks**: create/delete projects, tasks and subtasks with hierarchy,
  board column, dates, duration, % complete, milestones, dependencies (with cycle
  detection), people assignment with their dedication, priority, colored labels and
  comments.
- **Task dialog**: a tabbed window (General, Dates and progress, Assignments,
  Dependencies and Comments), a Markdown description with a formatting bar and preview,
  searchable pickers for the parent task and dependencies, a calendar with shortcuts
  (Today, Tomorrow, Next week), field-by-field validation and a warning about unsaved
  changes.
- **Views within a project** (Planner-style icon rail): List (flat listing with
  hierarchy indentation, text search and board-column filter, with priority and label
  columns), Kanban board (configurable columns, draggable cards), Gantt (bars with
  progress fill, milestones, dependency arrows, drag to move/resize, zoom and cascading
  propagation to children and dependents), Resources (create/edit, avatar, workload per
  person) and Resource usage (occupancy over time, with overload marked in red).
- **Global Gantt**: overlays the chosen projects on a single chart to spot overlaps
  between them.
- **Reports**: a visual panel with overall progress, tasks per status, progress
  breakdown (not started/in progress/completed) and date alerts (overdue, past
  planned end, due within 7 days, active resources).
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

Requires Python 3.11+, PyGObject and the system's GTK4.

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
