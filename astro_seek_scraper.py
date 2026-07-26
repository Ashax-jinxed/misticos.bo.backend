# astro_seek_scraper.py
"""
Módulo para consultar una URL de cálculo de astro-seek.com ya generada
y extraer la URL de la imagen de la rueda astrológica (radix) que
astro-seek devuelve en el HTML de resultado.
"""

import re
import requests
from urllib.parse import urlparse

DOMINIOS_PERMITIDOS = {
    "es.astro-seek.com",
    "astro-seek.com",
    "horoscopes.astro-seek.com",
}

# Regex para encontrar: <a id="radix_graf" ... href="...">
PATRON_RADIX = re.compile(r'id="radix_graf"[^>]*href="([^"]+)"')

# Regex de respaldo: <img ... src="...horoscope-chart...">, por si cambia el id
PATRON_IMG_RESPALDO = re.compile(r'<img[^>]*src="([^"]*horoscope-chart[^"]*)"')

HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}


def _validar_url_astroseek(url: str) -> None:
    """Lanza ValueError si la URL no apunta a un dominio permitido de astro-seek."""
    partes = urlparse(url)
    if partes.scheme not in ("http", "https"):
        raise ValueError("La URL debe usar http o https")
    if partes.netloc not in DOMINIOS_PERMITIDOS:
        raise ValueError(f"Dominio no permitido: {partes.netloc}")


def obtener_url_imagen_carta(url_calculo: str, timeout: int = 15) -> str:
    """
    Dada la URL completa de cálculo de astro-seek (la que ya generamos
    con fecha/hora/lat/long), consulta esa página y devuelve la URL
    de la imagen de la rueda astrológica en su versión de mayor resolución.

    Lanza ValueError o RuntimeError si algo falla, con un mensaje claro.
    """
    _validar_url_astroseek(url_calculo)

    try:
        respuesta = requests.get(
            url_calculo, headers=HEADERS_NAVEGADOR, timeout=timeout
        )
    except requests.RequestException as e:
        raise RuntimeError(f"No se pudo conectar a astro-seek: {e}")

    if respuesta.status_code != 200:
        raise RuntimeError(
            f"astro-seek respondió con estado {respuesta.status_code} "
            "(posible bloqueo anti-bot o URL inválida)"
        )

    html = respuesta.text

    # Intento 1: el link "Fullsize" (mejor resolución)
    match = PATRON_RADIX.search(html)
    if match:
        url_imagen = match.group(1).replace("&amp;", "&")
        return url_imagen

    # Intento 2 (respaldo): el <img src="..."> embebido
    match = PATRON_IMG_RESPALDO.search(html)
    if match:
        url_imagen = match.group(1).replace("&amp;", "&")
        return url_imagen

    raise RuntimeError(
        "No se encontró la imagen de la carta en la respuesta de astro-seek "
        "(puede que la página haya cambiado de estructura, o que faltaran "
        "datos válidos como latitud/longitud en la URL de cálculo)"
    )
