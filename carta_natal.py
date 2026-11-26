import os
from pathlib import Path

import swisseph as swe

from swe_lock import con_lock_swe

DEBUG = os.getenv("ASTRO_DEBUG", "0") == "1"


def _dbg(*args):
    if DEBUG:
        print(*args)


# Ruta de efemérides (se fija UNA vez al importar; swe.set_ephe_path() cierra los
# archivos abiertos, así que llamarlo en cada cálculo obligaba a reabrirlos).
BASE_DIR = Path(__file__).resolve().parent
EPHE_PATH = str(BASE_DIR / "ephe")
swe.set_ephe_path(EPHE_PATH)

_SIGNOS = (
    "ARIES", "TAURO", "GEMINIS", "CANCER", "LEO", "VIRGO",
    "LIBRA", "ESCORPIO", "SAGITARIO", "CAPRICORNIO", "ACUARIO", "PISCIS"
)

_PLANETAS = (
    ('SOL', swe.SUN),
    ('LUNA', swe.MOON),
    ('MERCURIO', swe.MERCURY),
    ('VENUS', swe.VENUS),
    ('MARTE', swe.MARS),
    ('JUPITER', swe.JUPITER),
    ('SATURNO', swe.SATURN),
    ('URANO', swe.URANUS),
    ('NEPTUNO', swe.NEPTUNE),
    ('PLUTON', swe.PLUTO),
)

_FLAGS_VEL = swe.FLG_SWIEPH | swe.FLG_SPEED


def obtener_signo_grado(longitud_ec):
    signo_index = int(longitud_ec // 30) % 12
    grado = (longitud_ec % 30)
    return _SIGNOS[signo_index], grado


@con_lock_swe
def calcular_carta_natal_sola(año, mes, dia, hora, minuto, latitud, longitud, zona_horaria, sistema_casas='P'):
    # Ajustar hora local a UTC
    hora_utc = hora - zona_horaria
    dia_utc = dia
    if hora_utc >= 24:
        hora_utc -= 24
        dia_utc += 1
    elif hora_utc < 0:
        hora_utc += 24
        dia_utc -= 1

    jd = swe.julday(año, mes, dia_utc, hora_utc + minuto / 60.0)

    casas_data = swe.houses(jd, latitud, longitud, b'P')
    cuspides_placidus = list(casas_data[0][:12])
    ascendente = casas_data[1][0]
    mc = casas_data[1][1]

    if DEBUG:
        _dbg(f"\n🐛 DEBUG ASC: {ascendente:.4f}° = {obtener_signo_grado(ascendente)[0]} {obtener_signo_grado(ascendente)[1]:.2f}°")
        _dbg(f"🐛 DEBUG MC: {mc:.4f}° = {obtener_signo_grado(mc)[0]} {obtener_signo_grado(mc)[1]:.2f}°")
        _dbg(f"🐛 MC == Cúspide 10? {abs(mc - cuspides_placidus[9]) < 0.01}")

    signo_ascendente = int(ascendente // 30) % 12

    if sistema_casas == 'W':
        cuspides = [(signo_ascendente * 30 + i * 30) % 360 for i in range(12)]

        def obtener_casa(long_ec):
            signo_punto = int(long_ec // 30) % 12
            return ((signo_punto - signo_ascendente) % 12) + 1

    else:
        cuspides = cuspides_placidus
        # pares (a, b) precalculados una vez en vez de recalcular índices en cada búsqueda
        tramos = [(cuspides[i], cuspides[(i + 1) % 12]) for i in range(12)]

        def obtener_casa(long_ec):
            for i, (a, b) in enumerate(tramos):
                long_n = long_ec
                b_n = b
                if b < a:
                    if long_ec < a:
                        long_n = long_ec + 360
                    b_n = b + 360
                if a <= long_n < b_n:
                    return i + 1
            return 12

    carta = {}

    # Planetas principales
    for nombre, num in _PLANETAS:
        res = swe.calc_ut(jd, num, _FLAGS_VEL)
        lon_p = float(res[0][0])
        velocidad = float(res[0][3])
        signo, grado = obtener_signo_grado(lon_p)
        carta[nombre] = {
            'signo': signo,
            'grado': float(grado),
            'casa': int(obtener_casa(lon_p)),
            'retrogrado': velocidad < 0,
            'longitud': lon_p
        }

    # Nodo norte y sur
    try:
        res = swe.calc_ut(jd, swe.TRUE_NODE, swe.FLG_SWIEPH)
        lon_n = float(res[0][0])
        signo, grado = obtener_signo_grado(lon_n)
        casa = obtener_casa(lon_n)
        _dbg(f"🐛 DEBUG Nodo Norte: {lon_n:.4f}° = {signo} {grado:.2f}° → Casa {casa}")

        carta['NODO_NORTE'] = {
            'signo': signo, 'grado': grado,
            'casa': casa, 'retrogrado': False,
            'longitud': lon_n
        }

        longitud_sur = (lon_n + 180) % 360
        signo_s, grado_s = obtener_signo_grado(longitud_sur)
        carta['NODO_SUR'] = {
            'signo': signo_s, 'grado': grado_s,
            'casa': obtener_casa(longitud_sur), 'retrogrado': False,
            'longitud': longitud_sur
        }

    except Exception as e:
        print("Nodo error:", e)

    # Lilith (apogeo osculante)
    try:
        res = swe.calc_ut(jd, swe.OSCU_APOG, swe.FLG_SWIEPH)
        lon_l = float(res[0][0])
        signo, grado = obtener_signo_grado(lon_l)
        carta['LILITH'] = {
            'signo': signo, 'grado': grado,
            'casa': obtener_casa(lon_l), 'retrogrado': False,
            'longitud': lon_l
        }
    except:
        pass

    # Quirón
    try:
        xx, ret = swe.calc_ut(jd, swe.CHIRON, _FLAGS_VEL)
        if ret < 0 or (ret & swe.FLG_SWIEPH) == 0:
            raise RuntimeError(
                f"Quirón sin efemérides (retflag={ret}). Revisá seas_18.se1 y sepl_18.se1 en {EPHE_PATH}"
            )
        lon_q = float(xx[0])
        signo, grado = obtener_signo_grado(lon_q)
        carta['QUIRON'] = {
            'signo': signo, 'grado': grado,
            'casa': obtener_casa(lon_q), 'retrogrado': False,
            'longitud': lon_q
        }
    except Exception as e:
        print("Quirón error:", e)
        carta['QUIRON'] = {
            'signo': 'N/A', 'grado': 0, 'casa': 0,
            'retrogrado': False, 'longitud': 0
        }

    # Parte de fortuna (fórmula día/noche)
    sol_long = carta['SOL']['longitud']
    luna_long = carta['LUNA']['longitud']
    es_diurna = carta['SOL']['casa'] >= 7

    if es_diurna:
        fortuna_long = (ascendente + luna_long - sol_long) % 360
    else:
        fortuna_long = (ascendente + sol_long - luna_long) % 360

    signo, grado = obtener_signo_grado(fortuna_long)
    casa = obtener_casa(fortuna_long)
    _dbg(f"🐛 DEBUG Parte Fortuna: {fortuna_long:.4f}° = {signo} {grado:.2f}° → Casa {casa}")

    carta['PARTE_FORTUNA'] = {
        'signo': signo, 'grado': grado,
        'casa': casa, 'retrogrado': False,
        'longitud': fortuna_long
    }

    # ASC y MC
    signo_asc, grado_asc = obtener_signo_grado(ascendente)
    carta['ASCENDENTE'] = {
        'signo': signo_asc, 'grado': grado_asc,
        'casa': 1, 'retrogrado': False, 'longitud': ascendente
    }

    signo_mc, grado_mc = obtener_signo_grado(mc)
    carta['MEDIO_CIELO'] = {
        'signo': signo_mc, 'grado': grado_mc,
        'casa': 10, 'retrogrado': False, 'longitud': mc
    }

    # cúspides en signos
    cuspides_signos = {
        str(idx): _SIGNOS[int(cdeg // 30) % 12]
        for idx, cdeg in enumerate(cuspides, start=1)
    }
    
    cuspides_grados = {
        str(idx): round(float(cdeg % 30), 4)
        for idx, cdeg in enumerate(cuspides, start=1)
    }
    
    if DEBUG:
        _dbg("\n🏠 CÚSPIDES PLACIDUS:")
        for i, cusp in enumerate(cuspides, start=1):
            signo_c, grado_c = obtener_signo_grado(cusp)
            _dbg(f"Casa {i}: {signo_c} {grado_c:.2f}° ({cusp:.2f}°)")

        return {
        "carta": carta,
        "cuspides": cuspides_signos,
        "cuspides_grados": cuspides_grados
        }   
