# GnoMilestone

Gestor de proyectos de escritorio para GNOME (GTK4/Adwaita), heredero espiritual de
GNOME Planner: proyectos, tareas y subtareas con diagrama de Gantt, lista de tareas y
tablero Kanban, con integración opcional con GitHub Issues y GitHub Projects.

En desarrollo: esta primera versión solo trae la ventana principal, el selector de
idioma/tema y el empaquetado `.deb` con CI/CD. La gestión de proyectos llega en las
próximas fases (ver `CHANGELOG.md`).

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

## Próximas tareas

- Definir una sección de Informes con gráficos configurables (circular, barras, líneas y
  araña) para consultar el cumplimiento y otras métricas del proyecto.

## Licencia

Este proyecto se distribuye bajo la GNU General Public License, versión 3 o posterior
(ver `COPYING`).
