"""Descarga de imágenes remotas de las notas (badges, logotipos) con caché en disco.

Sin GTK: `obtener` bloquea, así que se llama desde un hilo. Solo HTTPS (un README ajeno no
debe poder hacer que la aplicación consulte direcciones locales), con tope de tamaño y de
tiempo. La caché evita volver a pedir lo mismo cada vez que se abre la nota; si la red
falla se usa la copia caducada, y si no hay ninguna, None.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

TAMANO_MAXIMO = 5 * 1024 * 1024
TIEMPO_ESPERA = 10
VIGENCIA_SEGUNDOS = 24 * 3600  # los badges cambian (versión, estado del CI): se refrescan a diario


def carpeta_cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "gnomilestone" / "imagenes"


def es_descargable(url: str) -> bool:
    return url.lower().startswith("https://")


def _ruta(url: str) -> Path:
    return carpeta_cache() / hashlib.sha256(url.encode("utf-8")).hexdigest()


def obtener(url: str) -> bytes | None:
    """Bytes de la imagen, de la caché si está vigente, o None si no se pudo conseguir."""
    if not es_descargable(url):
        return None
    ruta = _ruta(url)
    copia: bytes | None = None
    try:
        if ruta.exists():
            copia = ruta.read_bytes()
            if time.time() - ruta.stat().st_mtime < VIGENCIA_SEGUNDOS:
                return copia
    except OSError:
        copia = None
    try:
        peticion = urllib.request.Request(url, headers={"User-Agent": "GnoMilestone"})
        with urllib.request.urlopen(peticion, timeout=TIEMPO_ESPERA) as respuesta:
            datos = respuesta.read(TAMANO_MAXIMO + 1)
    except Exception as e:  # noqa: BLE001 - cualquier fallo de red cae a la copia vieja
        log.debug("No se pudo descargar la imagen %s: %s", url, e)
        return copia
    if not datos or len(datos) > TAMANO_MAXIMO:
        return copia
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)
    except OSError as e:
        log.debug("No se pudo guardar en caché %s: %s", url, e)
    return datos
