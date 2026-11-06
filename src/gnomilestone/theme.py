from __future__ import annotations

import re


def theme_variant(name: str, dark: bool) -> str:
    """Deriva el nombre del tema GTK hermano (claro/oscuro) preservando el acento.

    Sigue la convención Mint-Y[-Dark]-<Acento> de Linux Mint y, para el resto de
    temas, la de Adwaita/Yaru (<tema>[-<acento>]-dark).
    """
    base = re.sub(r"-dark(?=-|$)", "", name, count=1, flags=re.IGNORECASE)
    if not dark:
        return base
    parts = base.split("-", 2)
    if parts[0] == "Mint" and len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}-Dark" + (f"-{parts[2]}" if len(parts) > 2 else "")
    return base + "-dark"


def is_dark_theme(name: str | None) -> bool:
    """Indica si un tema GTK corresponde a una variante oscura."""
    return bool(name and "-dark" in name.lower())
