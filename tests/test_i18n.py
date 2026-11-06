import gettext

from gnomilestone import i18n


def test_spanish_is_the_source_language_and_needs_no_catalog():
    assert i18n._("Preferencias") == "Preferencias"


def test_english_catalog_translates():
    translation = gettext.translation(
        i18n.DOMAIN, localedir=str(i18n.LOCALE_DIR), languages=["en"]
    )
    assert translation.gettext("Preferencias") == "Preferences"
    assert translation.gettext("Tema") == "Theme"


def test_english_mo_file_exists():
    mo_path = i18n.LOCALE_DIR / "en" / "LC_MESSAGES" / f"{i18n.DOMAIN}.mo"
    assert mo_path.exists(), "Falta compilar po/en.po (ver po/README.md)"


def test_formatear_fecha_local_espanol(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "es")
    assert i18n.formatear_fecha_local("2026-11-07") == "07/11/2026"


def test_formatear_fecha_local_no_espanol_usa_locale(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")
    # Sin prefijo "es" se usa %x del locale (aquí suele ser año de 2 cifras) o ISO.
    texto = i18n.formatear_fecha_local("2026-11-07")
    assert "11" in texto and "07" in texto
