# transitos.py  (versión optimizada - mismo comportamiento y resultados que el original)
"""
Módulo profesional A1 (precisión por hora).
Exporta:
 - calcular_transitos_cielo(fecha_inicio, fecha_final, incluir_luna=True)
 - calcular_transitos_natal(fecha_inicio, fecha_final, posiciones_natales=None, cuspides=None, incluir_luna=True)
 - calcular_transitos_completo(...)  -> combina ambos

Estrategia de optimización:
 1. Las efemérides horarias se calculan UNA sola vez (1 llamada a swe.calc_ut por
    planeta/hora, que devuelve longitud y velocidad) y se comparten entre tránsitos
    natales y tránsitos del cielo.
 2. La detección de aspectos / cambios de signo / casa / retrogradación se hace con
    numpy sobre arrays completos, en vez de iterar hora por hora en Python.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import swisseph as swe

from swe_lock import con_lock_swe

DEBUG = os.getenv("ASTRO_DEBUG", "0") == "1"


def _dbg(*args) -> None:
    if DEBUG:
        print(*args)


BASE_DIR = Path(__file__).resolve().parent
EPHE_PATH = str(BASE_DIR / "ephe")
os.makedirs(EPHE_PATH, exist_ok=True)
swe.set_ephe_path(EPHE_PATH)

PLANETAS = {
    'SOL': swe.SUN,
    'LUNA': swe.MOON,
    'MERCURIO': swe.MERCURY,
    'VENUS': swe.VENUS,
    'MARTE': swe.MARS,
    'JUPITER': swe.JUPITER,
    'SATURNO': swe.SATURN,
    'URANO': swe.URANUS,
    'NEPTUNO': swe.NEPTUNE,
    'PLUTON': swe.PLUTO
}

SIGNOS_NOMBRES = [
    "ARIES", "TAURO", "GÉMINIS", "CÁNCER", "LEO", "VIRGO",
    "LIBRA", "ESCORPIO", "SAGITARIO", "CAPRICORNIO", "ACUARIO", "PISCIS"
]

ASPECTOS = {
    "conjuncion": 0.0,
    "sextil": 60.0,
    "cuadratura": 90.0,
    "trigono": 120.0,
    "oposicion": 180.0
}

ASPECTOS_LABEL = {
    "conjuncion": "conjunción",
    "sextil": "sextil",
    "cuadratura": "cuadratura",
    "trigono": "trígono",
    "oposicion": "oposición"
}

ORBES_BASE = {
    "LUNA": 6.0,
    "SOL": 4.0,
    "MERCURIO": 3.0,
    "VENUS": 3.0,
    "MARTE": 2.5,
    "JUPITER": 2.0,
    "SATURNO": 2.0,
    "URANO": 1.5,
    "NEPTUNO": 1.5,
    "PLUTON": 1.5
}

DT_FMT = "%Y-%m-%d %H:%M"
DT_DAY_FMT = "%Y-%m-%d"

_UNA_HORA = timedelta(hours=1)
# calc_ut() usa estos mismos flags por defecto: una sola llamada da longitud y velocidad.
_FLAGS_EFEM = swe.FLG_SWIEPH | swe.FLG_SPEED
_ASPECTOS_ITEMS = list(ASPECTOS.items())


# ============================================================
# Utilidades escalares (se mantienen por compatibilidad)
# ============================================================
def _norm360(x: float) -> float:
    x = x % 360.0
    if x < 0:
        x += 360.0
    return x

def _ang_diff(a: float, b: float) -> float:
    diff = abs(_norm360(a) - _norm360(b))
    if diff > 180:
        diff = 360 - diff
    return diff

def distancia_aspecto(lon1: float, lon2: float, ang_obj: float) -> float:
    diff = _ang_diff(lon1, lon2)
    return abs(diff - ang_obj)

def _calc_long(jd: float, planeta_num: int) -> Optional[float]:
    try:
        return float(swe.calc_ut(jd, planeta_num)[0][0]) % 360.0
    except Exception:
        return None

def _fecha_str(dt: datetime) -> str:
    return dt.strftime(DT_FMT)

def _fecha_day_str(dt: datetime) -> str:
    return dt.strftime(DT_DAY_FMT)

def obtener_casa_desde_cuspides(long_ec: float, cuspides: List[float]) -> int:
    for i in range(12):
        a = cuspides[i]
        b = cuspides[(i + 1) % 12]
        long_n = long_ec
        b_n = b
        if b < a:
            if long_ec < a:
                long_n = long_ec + 360.0
            b_n = b + 360.0
        if a <= long_n < b_n:
            return i + 1
    return 12

def obtener_casa_desde_cuspides_o_wholesign(
    long_ec: float,
    cuspides: List[float],
    sistema: str = "P"
) -> int:
    """
    Calcula la casa según el sistema elegido.
    - P (Placidus): usa cúspides calculadas
    - W (Whole Sign): divide en 12 sectores desde el ASC
    """
    if sistema == "W":
        signo_punto = int(long_ec // 30) % 12
        signo_asc = int(cuspides[0] // 30) % 12  # cuspides[0] = ASC
        return ((signo_punto - signo_asc) % 12) + 1
    return obtener_casa_desde_cuspides(long_ec, cuspides)


# ============================================================
# Núcleo vectorizado
# ============================================================
def _lista_planetas(incluir_luna: bool) -> List[str]:
    planetas = list(PLANETAS.keys())
    if not incluir_luna and "LUNA" in planetas:
        planetas.remove("LUNA")
    return planetas


def _t_str(inicio_day: datetime, k: int) -> str:
    """Texto de la hora número k de la malla horaria."""
    return (inicio_day + timedelta(hours=int(k))).strftime(DT_FMT)


def _efemerides_horarias(inicio_day: datetime, final_day: datetime, planetas: List[str]) -> Dict[str, Any]:
    """
    Calcula longitud (NaN si swe falla) y retrogradación para cada hora y planeta.
    Misma malla que el original: desde inicio_day 00:00 hasta final_day 23:00, paso 1 h.
    """
    last_end = final_day + timedelta(hours=23)
    n = int((last_end - inicio_day) // _UNA_HORA) + 1 if last_end >= inicio_day else 0
    nums = [PLANETAS[p] for p in planetas]
    lon = np.full((n, len(planetas)), np.nan)
    retro = np.zeros((n, len(planetas)), dtype=bool)

    calc = swe.calc_ut
    julday = swe.julday
    fecha = inicio_day
    for k in range(n):
        jd = julday(fecha.year, fecha.month, fecha.day, fecha.hour)
        for c, num in enumerate(nums):
            try:
                xx = calc(jd, num, _FLAGS_EFEM)[0]
            except Exception:
                continue  # queda NaN: el original salta esa hora para ese planeta
            lon[k, c] = float(xx[0]) % 360.0
            retro[k, c] = float(xx[3]) < 0
        fecha += _UNA_HORA

    return {
        "inicio": inicio_day, "final": final_day, "n": n,
        "planetas": list(planetas), "lon": lon, "retro": retro,
        "last_fin": last_end.strftime(DT_FMT),
    }


def _obtener_efem(efem, inicio_day, final_day, planetas):
    if (efem is not None and efem["planetas"] == planetas
            and efem["inicio"] == inicio_day and efem["final"] == final_day):
        return efem
    return _efemerides_horarias(inicio_day, final_day, planetas)


def _asignar_posiciones_extremos(out, planetas, inicio_day, final_day) -> None:
    """Posición al mediodía del primer y último día (misma semántica de errores que el original)."""
    try:
        jd_ini = swe.julday(inicio_day.year, inicio_day.month, inicio_day.day, 12.0)
        jd_fin = swe.julday(final_day.year, final_day.month, final_day.day, 12.0)
        for p in planetas:
            n = PLANETAS[p]
            long_ini = _calc_long(jd_ini, n)
            long_fin = _calc_long(jd_fin, n)
            out[p]["posicion_inicial"] = {"longitud": float(long_ini), "grado": float(long_ini % 30)}
            out[p]["posicion_final"] = {"longitud": float(long_fin), "grado": float(long_fin % 30)}
    except Exception:
        pass


def _ventanas(dist: np.ndarray, orbe: float):
    """
    Todas las ventanas en orbe de una clave (planeta, punto, aspecto), en orden cronológico.
    Cada elemento: (i_inicio, i_exacto, i_fin | None); i_fin es la primera muestra fuera de
    orbe (None si sigue en orbe al terminar el período) e i_exacto el primer mínimo de la
    distancia dentro de la ventana. Así se reportan TODAS las pasadas (p. ej. por retrogradación).
    """
    dentro = dist <= orbe
    if not dentro.any():
        return []
    pad = np.concatenate(([False], dentro, [False]))
    cambios = np.flatnonzero(pad[1:] != pad[:-1])
    n = dist.shape[0]
    res = []
    for ini, fin in zip(cambios[0::2], cambios[1::2]):
        ini, fin = int(ini), int(fin)
        iex = ini + int(dist[ini:fin].argmin())
        res.append((ini, iex, None if fin >= n else fin))
    return res


def _dist_angular(lon_a: np.ndarray, lon_b) -> np.ndarray:
    """|a-b| plegado a [0, 180]. Las longitudes ya vienen normalizadas a [0, 360)."""
    d = np.abs(lon_a - lon_b)
    return np.where(d > 180.0, 360.0 - d, d)


def _casas_vectorizado(lon: np.ndarray, cuspides: List[float], sistema: str) -> np.ndarray:
    if sistema == "W":
        signo_pt = (lon // 30.0).astype(np.int64) % 12
        signo_asc = int(cuspides[0] // 30) % 12
        return ((signo_pt - signo_asc) % 12) + 1

    casa = np.full(lon.shape, 12, dtype=np.int64)
    libre = np.ones(lon.shape, dtype=bool)
    for i in range(12):
        a = cuspides[i]
        b = cuspides[(i + 1) % 12]
        if b < a:
            long_n = np.where(lon < a, lon + 360.0, lon)
            b_n = b + 360.0
        else:
            long_n = lon
            b_n = b
        m = libre & (a <= long_n) & (long_n < b_n)
        casa[m] = i + 1
        libre &= ~m
    return casa


# ============================================================
# TRANSITOS DEL CIELO (planeta vs planeta)
# ============================================================
@con_lock_swe
def calcular_transitos_cielo(fecha_inicio: str, fecha_final: str, incluir_luna: bool = True,
                             _efem: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    inicio_day = datetime.strptime(fecha_inicio, DT_DAY_FMT)
    final_day = datetime.strptime(fecha_final, DT_DAY_FMT)

    planetas = _lista_planetas(incluir_luna)
    out = {p: {"planeta": p, "posicion_inicial": None, "posicion_final": None, "eventos": []} for p in planetas}
    _asignar_posiciones_extremos(out, planetas, inicio_day, final_day)

    ef = _obtener_efem(_efem, inicio_day, final_day, planetas)
    n, lon, last_fin = ef["n"], ef["lon"], ef["last_fin"]
    np_ = len(planetas)
    # por planeta: lista de (clave_orden_fecha, secuencia_original, evento)
    acum: List[list] = [[] for _ in range(np_)]

    if n > 0:
        valido = ~np.isnan(lon)
        for i in range(np_):
            for j in range(i + 1, np_):
                p1, p2 = planetas[i], planetas[j]
                idx = np.flatnonzero(valido[:, i] & valido[:, j])
                if idx.size == 0:
                    continue
                d = _dist_angular(lon[idx, i], lon[idx, j])
                orbe = min(ORBES_BASE.get(p1, 2.0), ORBES_BASE.get(p2, 2.0))

                for a, (asp_name, ang) in enumerate(_ASPECTOS_ITEMS):
                    for i0, iex, i1 in _ventanas(np.abs(d - ang), orbe):
                        t0, tex = int(idx[i0]), int(idx[iex])
                        f_ini = _t_str(inicio_day, t0)
                        f_ex = _t_str(inicio_day, tex)
                        if i1 is not None:
                            t1 = int(idx[i1])
                            f_fin = _t_str(inicio_day, t1)
                            seq = (t1, 0, i, j, a)          # se cierra durante el bucle
                        else:
                            f_fin = last_fin
                            seq = (n + 1, t0, i, j, a)      # se cierra al final, en orden de apertura
                        evento = {
                            "tipo": "aspecto_transito",
                            "origen": "transito_transito",
                            "planeta1": p1,
                            "planeta2": p2,
                            "aspecto": asp_name,
                            "descripcion": f"{p1} {ASPECTOS_LABEL.get(asp_name, asp_name)} {p2}",
                            "fecha_inicio": f_ini,
                            "fecha_exacto": f_ex,
                            "fecha_fin": f_fin
                        }
                        item = (f_ex, seq, evento)
                        acum[i].append(item)
                        acum[j].append(item)

    resultado = []
    for c, p in enumerate(planetas):
        # 'YYYY-MM-DD HH:MM' ordena igual como texto que como datetime; seq conserva el
        # orden de inserción original para los empates (equivale al sort estable previo).
        acum[c].sort(key=lambda it: (it[0], it[1]))
        out[p]["eventos"] = [it[2] for it in acum[c]]
        resultado.append(out[p])
    return resultado


# ============================================================
# TRANSITOS SOBRE CARTA NATAL
# ============================================================
@con_lock_swe
def calcular_transitos_natal(
    fecha_inicio: str,
    fecha_final: str,
    posiciones_natales: Optional[Dict[str, float]] = None,
    cuspides: Optional[List[float]] = None,  # ← Mantener para compatibilidad
    incluir_luna: bool = True,
    sistema: str = "P",
    año_natal: Optional[int] = None,
    mes_natal: Optional[int] = None,
    dia_natal: Optional[int] = None,
    hora_natal: Optional[int] = None,
    minuto_natal: Optional[int] = None,
    latitud_natal: Optional[float] = None,
    longitud_natal: Optional[float] = None,
    zona_horaria_natal: int = -4,
    _efem: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:

    inicio_day = datetime.strptime(fecha_inicio, DT_DAY_FMT)
    final_day = datetime.strptime(fecha_final, DT_DAY_FMT)

    # ---- Cúspides (si no se proporcionaron) ----
    if cuspides is None:
        if all(v is not None for v in (año_natal, mes_natal, dia_natal, latitud_natal, longitud_natal)):
            hora_c = 12 if hora_natal is None else hora_natal      # 0 (medianoche) es válido
            minuto_c = 0 if minuto_natal is None else minuto_natal
            _dbg(f"🔍 DEBUG: Intentando calcular cúspides con: {año_natal}-{mes_natal}-{dia_natal} "
                 f"{hora_c}:{minuto_c} lat={latitud_natal} lon={longitud_natal} sistema={sistema}")
            try:
                cuspides = calcular_cuspides_desde_natal(
                    año_natal, mes_natal, dia_natal,
                    hora_c, minuto_c,
                    latitud_natal, longitud_natal,
                    sistema,
                    zona_horaria_natal
                )
                if cuspides and len(cuspides) == 12:
                    _dbg(f"✅ Cúspides calculadas internamente: {len(cuspides)}")
                else:
                    _dbg("⚠️ No se pudieron calcular cúspides - no habrá cambios de casa")
            except Exception as e:
                print(f"❌ ERROR CALCULANDO CÚSPIDES: {e}")
                import traceback
                traceback.print_exc()
                cuspides = None
        else:
            _dbg("⚠️ Faltan datos natales para calcular cúspides")
    else:
        _dbg(f"✅ Usando cúspides proporcionadas: {len(cuspides)}")

    planetas = _lista_planetas(incluir_luna)
    out = {
        p: {"planeta": p, "posicion_inicial": None, "posicion_final": None, "eventos": []}
        for p in planetas
    }
    _asignar_posiciones_extremos(out, planetas, inicio_day, final_day)

    ef = _obtener_efem(_efem, inicio_day, final_day, planetas)
    n, lon, retro, last_fin = ef["n"], ef["lon"], ef["retro"], ef["last_fin"]
    usar_casas = bool(cuspides) and len(cuspides) == 12

    natales = []
    if posiciones_natales:
        natales = [(nombre, _norm360(natal_long)) for nombre, natal_long in posiciones_natales.items()]

    resultado = []
    for c, p in enumerate(planetas):
        evs: list = []   # (clave_orden_fecha, secuencia_original, evento)
        idx = np.flatnonzero(~np.isnan(lon[:, c])) if n > 0 else np.empty(0, dtype=np.int64)

        if idx.size > 0:
            lon_p = lon[idx, c]

            # --- cambios de signo ---
            signo = (lon_p // 30.0).astype(np.int64) % 12
            for k in np.flatnonzero(signo[1:] != signo[:-1]) + 1:
                t = int(idx[k])
                f = _t_str(inicio_day, t)
                nuevo = int(signo[k])
                evs.append((f, (t, 0, 0, 0), {
                    "tipo": "cambio_signo",
                    "origen": "evento_transito",
                    "planeta": p,
                    "signo_anterior": int(signo[k - 1]),
                    "signo_nuevo": nuevo,
                    "descripcion": f"{p} ingresa a {SIGNOS_NOMBRES[nuevo]}",
                    "fecha": f
                }))

            # --- cambios de casa ---
            if usar_casas:
                casa = _casas_vectorizado(lon_p, cuspides, sistema)
                for k in np.flatnonzero(casa[1:] != casa[:-1]) + 1:
                    t = int(idx[k])
                    f = _t_str(inicio_day, t)
                    nueva = int(casa[k])
                    evs.append((f, (t, 1, 0, 0), {
                        "tipo": "cambio_casa",
                        "origen": "evento_transito",
                        "planeta": p,
                        "casa_anterior": int(casa[k - 1]),
                        "casa_nueva": nueva,
                        "casa": nueva,
                        "descripcion": f"{p} ingresa a casa {nueva}",
                        "fecha": f
                    }))

            # --- retrogradación ---
            r = retro[idx, c]
            for k in np.flatnonzero(r[1:] != r[:-1]) + 1:
                t = int(idx[k])
                f = _t_str(inicio_day, t)
                is_retro = bool(r[k])
                evs.append((f, (t, 2, 0, 0), {
                    "tipo": "retro_inicio" if is_retro else "retro_fin",
                    "origen": "evento_transito",
                    "planeta": p,
                    "descripcion": f"{p} {'inicia' if is_retro else 'termina'} movimiento retrógrado",
                    "fecha": f
                }))

            # --- aspectos tránsito → natal ---
            for ni, (natal_name, natal_long) in enumerate(natales):
                d = _dist_angular(lon_p, natal_long)
                orbe = min(ORBES_BASE.get(p, 2.0),
                           ORBES_BASE.get(natal_name, ORBES_BASE.get(p, 2.0)))
                for a, (asp_name, ang) in enumerate(_ASPECTOS_ITEMS):
                    for i0, iex, i1 in _ventanas(np.abs(d - ang), orbe):
                        t0, tex = int(idx[i0]), int(idx[iex])
                        f_ini = _t_str(inicio_day, t0)
                        f_ex = _t_str(inicio_day, tex)
                        if i1 is not None:
                            t1 = int(idx[i1])
                            f_fin = _t_str(inicio_day, t1)
                            seq = (t1, 3, ni, a)
                        else:
                            f_fin = last_fin
                            seq = (n + 1, t0, ni, a)
                        evs.append((f_ex, seq, {
                            "tipo": "aspecto",
                            "origen": "transito_natal",
                            "planeta_transito": p,
                            "planeta_natal": natal_name,
                            "aspecto": asp_name,
                            "descripcion": f"{p} {ASPECTOS_LABEL.get(asp_name, asp_name)} {natal_name}",
                            "fecha_inicio": f_ini,
                            "fecha_exacto": f_ex,
                            "fecha_fin": f_fin
                        }))

        evs.sort(key=lambda it: (it[0], it[1]))
        out[p]["eventos"] = [it[2] for it in evs]
        resultado.append(out[p])

    return resultado


# ============================================================
# COMBINADOR
# ============================================================
@con_lock_swe
def calcular_transitos_completo(
    fecha_inicio: str,
    fecha_final: str,
    posiciones_natales: Optional[Dict[str, float]] = None,
    cuspides: Optional[List[float]] = None,
    incluir_luna: bool = True,
    incluir_cielo: bool = True,
    sistema: str = "P",
    año_natal: Optional[int] = None,
    mes_natal: Optional[int] = None,
    dia_natal: Optional[int] = None,
    hora_natal: Optional[int] = None,
    minuto_natal: Optional[int] = None,
    latitud_natal: Optional[float] = None,
    longitud_natal: Optional[float] = None,
    zona_horaria_natal: int = -4
) -> Dict[str, Any]:
    salida = {
        "periodo": {"inicio": fecha_inicio, "fin": fecha_final},
        "transitos_natal": [],
        "transitos_cielo": [],
        "eclipses": [],
        "fases_lunares": []
    }

    # Efemérides horarias calculadas una sola vez y compartidas por ambos cálculos.
    efem = None
    if posiciones_natales or incluir_cielo:
        inicio_day = datetime.strptime(fecha_inicio, DT_DAY_FMT)
        final_day = datetime.strptime(fecha_final, DT_DAY_FMT)
        efem = _efemerides_horarias(inicio_day, final_day, _lista_planetas(incluir_luna))

    if posiciones_natales:
        salida["transitos_natal"] = calcular_transitos_natal(
            fecha_inicio, fecha_final, posiciones_natales, cuspides, incluir_luna,
            sistema=sistema,
            año_natal=año_natal,
            mes_natal=mes_natal,
            dia_natal=dia_natal,
            hora_natal=hora_natal,
            minuto_natal=minuto_natal,
            latitud_natal=latitud_natal,
            longitud_natal=longitud_natal,
            zona_horaria_natal=zona_horaria_natal,
            _efem=efem
        )

    if incluir_cielo:
        salida["transitos_cielo"] = calcular_transitos_cielo(
            fecha_inicio, fecha_final, incluir_luna, _efem=efem
        )

    salida["eclipses"] = calcular_eclipses(fecha_inicio, fecha_final)
    salida["fases_lunares"] = calcular_fases_lunares(fecha_inicio, fecha_final)

    return salida


# ============================================================
# ECLIPSES (sin cambios de lógica)
# ============================================================
def _buscar_eclipses(fn_when, jd_inicio: float, jd_fin_excl: float):
    """
    Recorre TODOS los eclipses del rango. Tras cada eclipse se avanza solo 1 día (los eclipses
    del mismo tipo distan >= ~1 lunación), en vez de 170 días, que podía saltarse el segundo
    eclipse de una misma temporada.
    """
    jd = jd_inicio - 1
    while True:
        res = fn_when(jd, swe.FLG_SWIEPH)
        jd_eclipse = res[1][0]
        if jd_eclipse >= jd_fin_excl:
            return
        if jd_eclipse >= jd_inicio:
            yield res, jd_eclipse
        jd = jd_eclipse + 1


@con_lock_swe
def calcular_eclipses(fecha_inicio: str, fecha_final: str) -> List[Dict[str, Any]]:
    inicio_day = datetime.strptime(fecha_inicio, DT_DAY_FMT)
    final_day = datetime.strptime(fecha_final, DT_DAY_FMT)

    jd_inicio = swe.julday(inicio_day.year, inicio_day.month, inicio_day.day, 0)
    # fin exclusivo = 00:00 del día siguiente (incluye todo el último día, antes se cortaba a las 23:59:24)
    jd_fin_excl = swe.julday(final_day.year, final_day.month, final_day.day, 0) + 1

    eclipses = []

    # 🌞 ECLIPSES SOLARES
    for res, jd_eclipse in _buscar_eclipses(swe.sol_eclipse_when_glob, jd_inicio, jd_fin_excl):
        y, m, d = swe.revjul(jd_eclipse)[:3]
        long_sol = _calc_long(jd_eclipse, swe.SUN)
        signo = SIGNOS_NOMBRES[int(long_sol // 30)]

        flags = res[0]
        if flags & swe.ECL_TOTAL:
            tipo = "Eclipse Solar Total"
        elif flags & swe.ECL_ANNULAR:
            tipo = "Eclipse Solar Anular"
        elif flags & swe.ECL_PARTIAL:
            tipo = "Eclipse Solar Parcial"
        else:
            tipo = "Eclipse Solar"

        eclipses.append({
            "tipo": "eclipse",
            "subtipo": "solar",
            "descripcion": f"{tipo} en {signo}",
            "fecha": f"{y}-{m:02d}-{d:02d}",
            "signo": signo,
            "grado": long_sol % 30,
            "planeta": "SOL"
        })

    # 🌕 ECLIPSES LUNARES
    for res, jd_eclipse in _buscar_eclipses(swe.lun_eclipse_when, jd_inicio, jd_fin_excl):
        y, m, d = swe.revjul(jd_eclipse)[:3]
        long_luna = _calc_long(jd_eclipse, swe.MOON)
        signo = SIGNOS_NOMBRES[int(long_luna // 30)]

        flags = res[0]
        if flags & swe.ECL_TOTAL:
            tipo = "Eclipse Lunar Total"
        elif flags & swe.ECL_PARTIAL:
            tipo = "Eclipse Lunar Parcial"
        elif flags & swe.ECL_PENUMBRAL:
            tipo = "Eclipse Lunar Penumbral"
        else:
            tipo = "Eclipse Lunar"

        eclipses.append({
            "tipo": "eclipse",
            "subtipo": "lunar",
            "descripcion": f"{tipo} en {signo}",
            "fecha": f"{y}-{m:02d}-{d:02d}",
            "signo": signo,
            "grado": long_luna % 30,
            "planeta": "LUNA"
        })

    return eclipses


# ============================================================
# FASES LUNARES
# ============================================================
_OBJETIVOS_FASES = [
    ("Luna Nueva", 0),
    ("Cuarto Creciente", 90),
    ("Luna Llena", 180),
    ("Cuarto Menguante", 270)
]

@con_lock_swe
def calcular_fases_lunares(fecha_inicio: str, fecha_final: str) -> List[Dict[str, Any]]:
    """
    Calcula Luna Nueva, Cuarto Creciente, Luna Llena y Cuarto Menguante
    buscando el momento exacto de elongación = 0°, 90°, 180°, 270°.
    """
    inicio = datetime.strptime(fecha_inicio, DT_DAY_FMT)
    fin = datetime.strptime(fecha_final, DT_DAY_FMT)

    fases = []
    objetivos = _OBJETIVOS_FASES

    # Paso 1: escaneo grueso cada 6 horas
    delta_grueso = timedelta(hours=6)
    candidatos = {nombre: [] for nombre, _ in objetivos}

    fecha = inicio
    limite_grueso = fin + timedelta(days=1)
    while fecha <= limite_grueso:
        jd = swe.julday(fecha.year, fecha.month, fecha.day, fecha.hour + fecha.minute / 60.0)

        lon_sol = _calc_long(jd, swe.SUN)
        lon_luna = _calc_long(jd, swe.MOON)

        if lon_sol is not None and lon_luna is not None:
            elong = (lon_luna - lon_sol) % 360
            for nombre, ang_obj in objetivos:
                dist = min(abs(elong - ang_obj), 360 - abs(elong - ang_obj))
                if dist < 45:
                    candidatos[nombre].append((fecha, dist, elong))

        fecha += delta_grueso

    # Paso 2: refinar cada candidato con búsqueda fina
    delta_fino = timedelta(minutes=15)
    for nombre, ang_obj in objetivos:
        regiones = candidatos[nombre]
        if not regiones:
            continue

        regiones.sort(key=lambda x: x[0])
        ventanas = []
        ventana_actual = [regiones[0]]

        for i in range(1, len(regiones)):
            if regiones[i][0] - ventana_actual[-1][0] < timedelta(days=3):
                ventana_actual.append(regiones[i])
            else:
                ventanas.append(ventana_actual)
                ventana_actual = [regiones[i]]
        ventanas.append(ventana_actual)

        for ventana in ventanas:
            mejor = min(ventana, key=lambda x: x[1])
            fecha_base = mejor[0]

            mejor_dist = 999
            mejor_fecha = fecha_base
            mejor_lon_luna = None  # se reutiliza al final en vez de recalcular

            fecha_busqueda = fecha_base - timedelta(hours=12)
            fecha_limite = fecha_base + timedelta(hours=12)

            while fecha_busqueda <= fecha_limite:
                jd = swe.julday(fecha_busqueda.year, fecha_busqueda.month,
                                fecha_busqueda.day,
                                fecha_busqueda.hour + fecha_busqueda.minute / 60.0)

                lon_sol = _calc_long(jd, swe.SUN)
                lon_luna = _calc_long(jd, swe.MOON)

                if lon_sol is not None and lon_luna is not None:
                    elong = (lon_luna - lon_sol) % 360
                    dist = min(abs(elong - ang_obj), 360 - abs(elong - ang_obj))

                    if dist < mejor_dist:
                        mejor_dist = dist
                        mejor_fecha = fecha_busqueda
                        mejor_lon_luna = lon_luna

                fecha_busqueda += delta_fino

            if inicio <= mejor_fecha <= fin + timedelta(days=1):
                lon_luna_final = mejor_lon_luna
                if lon_luna_final is None:
                    jd_final = swe.julday(mejor_fecha.year, mejor_fecha.month, mejor_fecha.day,
                                          mejor_fecha.hour + mejor_fecha.minute / 60.0)
                    lon_luna_final = _calc_long(jd_final, swe.MOON)
                if lon_luna_final is not None:
                    signo = SIGNOS_NOMBRES[int(lon_luna_final // 30)]
                    fases.append({
                        "tipo": "fase_lunar",
                        "subtipo": nombre,
                        "descripcion": f"{nombre} en {signo}",
                        "fecha": mejor_fecha.strftime("%Y-%m-%d %H:%M:%S"),
                        "signo": signo,
                        "grado": lon_luna_final % 30,
                        "planeta": "LUNA",
                        "_debug_dist": f"{mejor_dist:.3f}°"
                    })

    fases.sort(key=lambda x: x["fecha"])

    # Eliminar duplicados del mismo tipo a menos de 1 hora (cada fecha se parsea una sola vez)
    fases_unicas = []
    vistas: Dict[str, List[datetime]] = {}
    for fase in fases:
        fecha_fase = datetime.strptime(fase["fecha"], "%Y-%m-%d %H:%M:%S")
        previas = vistas.setdefault(fase["subtipo"], [])
        if any(abs((fecha_fase - f).total_seconds()) < 3600 for f in previas):
            continue
        previas.append(fecha_fase)
        fases_unicas.append(fase)

    _dbg(f"DEBUG: Encontradas {len(fases_unicas)} fases lunares entre {fecha_inicio} y {fecha_final}")

    return fases_unicas


# --- Calcular cúspides (casa) desde fecha/hora natal y coordenadas ---
@con_lock_swe
def calcular_cuspides_desde_natal(year: int, month: int, day: int, hour: int, minute: int,
                                  lat: float, lon: float, sistema: str = "P",
                                  zona_horaria: int = -4) -> List[float]:
    """
    Devuelve lista de 12 cúspides (grados eclípticos) usando swe.houses.
    IMPORTANTE: Ajusta hora local a UTC antes de calcular.
    """
    _dbg(f"🏠 calcular_cuspides_desde_natal() {year}-{month}-{day} {hour}:{minute} "
         f"lat={lat} lon={lon} sistema={sistema} TZ={zona_horaria}")

    hora_utc = hour - zona_horaria
    dia_utc = day
    if hora_utc >= 24:
        hora_utc -= 24
        dia_utc += 1
    elif hora_utc < 0:
        hora_utc += 24
        dia_utc -= 1

    jd = swe.julday(year, month, dia_utc, hora_utc + (0 if minute is None else minute) / 60.0)

    try:
        cusps, ascmc = swe.houses(jd, lat, lon, b'P')
        _dbg(f"   ✅ ASC: {ascmc[0]:.2f}°, MC: {ascmc[1]:.2f}°")
        return [float(c) for c in cusps[:12]]
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None
