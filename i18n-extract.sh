#!/bin/sh
# Regenera po/gnomilestone.pot a partir del código fuente (strings envueltos en _())
# y actualiza las traducciones existentes (po/*.po) con las cadenas nuevas.
# Ejecutar a mano cada vez que se añade o cambia un texto de la interfaz.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
domain=gnomilestone

command -v xgettext >/dev/null 2>&1 || { echo "Falta xgettext (instala gettext)." >&2; exit 1; }
command -v msgmerge >/dev/null 2>&1 || { echo "Falta msgmerge (instala gettext)." >&2; exit 1; }

find "$base/src" -name "*.py" | sort > "$base/.i18n-files"
xgettext \
    --language=Python \
    --keyword=_ \
    --from-code=UTF-8 \
    --package-name="$domain" \
    --package-version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$base/pyproject.toml")" \
    --msgid-bugs-address=jose.antonio.seguido@gmail.com \
    --output="$base/po/$domain.pot" \
    --files-from="$base/.i18n-files"
rm -f "$base/.i18n-files"
echo "Plantilla actualizada: po/$domain.pot"

for po in "$base"/po/*.po; do
    [ -e "$po" ] || continue
    msgmerge --update --backup=off "$po" "$base/po/$domain.pot"
    echo "Actualizado $po (revisa las cadenas marcadas como fuzzy o nuevas)"
done
