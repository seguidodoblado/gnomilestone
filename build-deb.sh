#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
stage="$base/.deb-stage"
version=$(sed -n '1s/^[^ ]* (\([^)]*\)).*/\1/p' "$base/debian/changelog")
test -n "$version" || { echo "No se pudo leer la versión de debian/changelog" >&2; exit 1; }
upstream=${version%-*}
project_version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$base/pyproject.toml")
init_version=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$base/src/gnomilestone/__init__.py")
test "$upstream" = "$project_version" -a "$upstream" = "$init_version" || {
    echo "Versiones distintas: debian/changelog ($upstream), pyproject.toml ($project_version), __init__.py ($init_version)." >&2
    exit 1
}
package="$base/../gnomilestone_${version}_all.deb"
command -v dpkg-deb >/dev/null 2>&1 || { echo "Falta dpkg-deb (instala dpkg-dev)." >&2; exit 1; }
sh "$base/i18n-compile.sh"
rm -rf "$stage"
doc="$stage/usr/share/doc/gnomilestone"
mkdir -p "$stage/DEBIAN" "$stage/usr/share/gnomilestone" "$stage/usr/bin" "$stage/usr/share/applications" "$stage/usr/share/icons/hicolor/scalable/apps" "$doc"
cp -a "$base/src/gnomilestone" "$stage/usr/share/gnomilestone/"
find "$stage/usr/share/gnomilestone" -type d -name __pycache__ -prune -exec rm -rf {} +
cp "$base/debian/gnomilestone-launcher" "$stage/usr/bin/gnomilestone"
cp "$base/debian/gnomilestone.desktop" "$stage/usr/share/applications/"
cp "$base/src/gnomilestone/assets/gnomilestone.svg" "$stage/usr/share/icons/hicolor/scalable/apps/"
cp "$base/debian/copyright" "$doc/copyright"
gzip -9n -c "$base/debian/changelog" > "$doc/changelog.Debian.gz"
# Páginas de manual (inglés en man1, español en es/man1); la versión se rellena aquí
mkdir -p "$stage/usr/share/man/man1" "$stage/usr/share/man/es/man1"
sed "s/@VERSION@/${version}/" "$base/debian/gnomilestone.1" | gzip -9n > "$stage/usr/share/man/man1/gnomilestone.1.gz"
sed "s/@VERSION@/${version}/" "$base/debian/gnomilestone.es.1" | gzip -9n > "$stage/usr/share/man/es/man1/gnomilestone.1.gz"
cp "$base/debian/postinst" "$stage/DEBIAN/postinst"
# Permisos fijos (no dependen de la umask de quien construye): 755 en directorios, 644 en ficheros
find "$stage" -type d -exec chmod 755 {} +
find "$stage" -type f -exec chmod 644 {} +
cat > "$stage/DEBIAN/control" <<EOF
Package: gnomilestone
Version: ${version}
Section: devel
Priority: optional
Architecture: all
Depends: python3, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0 (>= 4.10)
Maintainer: Jose Antonio Seguido Doblado <jose.antonio.seguido@gmail.com>
Homepage: https://github.com/seguidodoblado/gnomilestone
Description: Gestor de proyectos con diagrama de Gantt e integración con GitHub
 Aplicación GTK para gestionar proyectos, tareas y subtareas con un
 diagrama de Gantt interactivo, vista de tabla y tablero Kanban, con
 vinculación opcional a Issues y Projects de GitHub.
EOF
chmod 644 "$stage/DEBIAN/control"
chmod 755 "$stage/usr/bin/gnomilestone"
chmod 755 "$stage/DEBIAN/postinst"
(cd "$stage" && find . -type f ! -path './DEBIAN/*' -printf '%P\n' | LC_ALL=C sort | xargs -d '\n' md5sum > DEBIAN/md5sums)
chmod 644 "$stage/DEBIAN/md5sums"
dpkg-deb --build --root-owner-group "$stage" "$package"
rm -rf "$stage"
echo "Paquete generado: $package"
