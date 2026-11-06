# Traducciones (i18n)

El idioma fuente del código es **español**: los textos de la interfaz se
escriben directamente en español dentro del código (`_("Preferencias")`),
y no hace falta ningún catálogo `es.po` — si no hay traducción cargada,
`gettext` devuelve el texto tal cual.

## Añadir o cambiar un texto de la interfaz

1. Envuelve el texto en `_(...)` (importado de `gnomilestone.i18n`).
2. **No** metas la llamada a `_()` dentro de una f-string (`f"...{_('texto')}..."`):
   `xgettext` no la detecta ahí. Saca el texto a una variable antes:
   ```python
   # mal — xgettext no ve "Texto":
   mensaje = f"Hola {_('Texto')}"
   # bien:
   texto = _("Texto")
   mensaje = f"Hola {texto}"
   ```
3. Ejecuta `./i18n-extract.sh` desde la raíz del proyecto. Regenera
   `po/gnomilestone.pot` y actualiza `po/*.po` con las cadenas nuevas (quedan con
   `msgstr ""` o marcadas `#, fuzzy` si el texto original cambió).
4. Traduce las cadenas nuevas/fuzzy a mano en `po/en.po` (o el idioma que
   corresponda) y quita la marca `#, fuzzy` una vez revisadas.
5. Ejecuta `./i18n-compile.sh` para generar los `.mo` y probarlo en la app:
   ```sh
   LANGUAGE=en python -m gnomilestone.app
   ```

`build-deb.sh` ya llama a `i18n-compile.sh` automáticamente, así que no hace
falta compilar a mano antes de empaquetar.

## Añadir un idioma nuevo

```sh
msginit --input=po/gnomilestone.pot --locale=<código> --output=po/<código>.po
```

Traduce `po/<código>.po` y compílalo con `./i18n-compile.sh` — detecta
cualquier `po/*.po` automáticamente, no hace falta tocar el script.

## Créditos de traducción

El «Acerca de» muestra quién tradujo cada idioma con `translator_credits=_("translator-credits")`. Es una
cadena más del catálogo: en `po/<código>.po`, rellena el `msgstr` de la entrada `translator-credits` con los
traductores, uno por línea (`\n`) y con `<correo>` opcional:

```po
msgid "translator-credits"
msgstr ""
"Nombre Apellido <correo@ejemplo.org>\n"
"Otra Persona"
```

Si un idioma no la traduce, GTK oculta la sección (es lo que pasa con el español, que no tiene catálogo).
No cambies el `msgid ""` de la cabecera del fichero: ese es el de la cabecera, no el de los créditos.

## Dónde vive cada cosa

- `po/*.po`, `po/gnomilestone.pot` — fuente de las traducciones, versionado en git.
- `src/gnomilestone/i18n/<idioma>/LC_MESSAGES/gnomilestone.mo` — catálogo compilado,
  **no** se versiona (está en `.gitignore`), se genera con `i18n-compile.sh`.
- `src/gnomilestone/i18n/__init__.py` — `install()` (llamar una vez al arrancar la
  app) y `_()` (domain-bound, úsalo en el código específico de la app).
