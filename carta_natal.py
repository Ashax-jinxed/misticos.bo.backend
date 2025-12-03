import swisseph as swe
import os
from pathlib import Path

# Ruta de efemérides
BASE_DIR = Path(__file__).resolve().parent
EPHE_PATH = str(BASE_DIR / "ephe")
swe.set_ephe_path(EPHE_PATH)

def obtener_signo_grado(longitud_ec):
    signos = [
        "ARIES","TAURO","GEMINIS","CANCER","LEO","VIRGO",
        "LIBRA","ESCORPIO","SAGITARIO","CAPRICORNIO","ACUARIO","PISCIS"
    ]
    signo_index = int(longitud_ec // 30) % 12
    grado = (longitud_ec % 30)
    return signos[signo_index], grado


def calcular_carta_natal_sola(año, mes, dia, hora, minuto, latitud, longitud, zona_horaria, sistema_casas='P'):
    swe.set_ephe_path(EPHE_PATH)

    # Ajustar hora local a UTC
    hora_utc = hora - zona_horaria
    dia_utc = dia
    if hora_utc >= 24:
        hora_utc -= 24
        dia_utc += 1
    elif hora_utc < 0:
        hora_utc += 24
        dia_utc -= 1

    jd = swe.julday(año, mes, dia_utc, hora_utc + minuto/60.0)

    casas_data = swe.houses(jd, latitud, longitud, b'P')
    cuspides_placidus = list(casas_data[0][:12])
    ascendente = casas_data[1][0]
    mc = casas_data[1][1]
    signo_ascendente = int(ascendente // 30) % 12

    if sistema_casas == 'W':
        cuspides = [(signo_ascendente * 30 + i * 30) % 360 for i in range(12)]

        def obtener_casa(long_ec):
            signo_punto = int(long_ec // 30) % 12
            return ((signo_punto - signo_ascendente) % 12) + 1

    else:
        cuspides = cuspides_placidus

        def obtener_casa(long_ec):
            for i in range(12):
                a = cuspides[i]
                b = cuspides[(i + 1) % 12]
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
    planetas = {
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

    for nombre, num in planetas.items():
        res = swe.calc_ut(jd, num, swe.FLG_SWIEPH | swe.FLG_SPEED)
        longitud = float(res[0][0])
        velocidad = float(res[0][3])
        signo, grado = obtener_signo_grado(longitud)
        casa = obtener_casa(longitud)
        carta[nombre] = {
            'signo': signo,
            'grado': float(grado),
            'casa': int(casa),
            'retrogrado': velocidad < 0,
            'longitud': longitud
        }

    # Nodo norte y sur
    try:
        res = swe.calc_ut(jd, swe.TRUE_NODE)
        longitud = float(res[0][0])
        signo, grado = obtener_signo_grado(longitud)
        casa = obtener_casa(longitud)
        carta['NODO_NORTE'] = {
            'signo': signo, 'grado': grado,
            'casa': casa, 'retrogrado': False,
            'longitud': longitud
        }

        longitud_sur = (longitud + 180) % 360
        signo_s, grado_s = obtener_signo_grado(longitud_sur)
        casa_s = obtener_casa(longitud_sur)
        carta['NODO_SUR'] = {
            'signo': signo_s, 'grado': grado_s,
            'casa': casa_s, 'retrogrado': False,
            'longitud': longitud_sur
        }

    except Exception as e:
        print("Nodo error:", e)

    # Lilith
    try:
        res = swe.calc_ut(jd, swe.MEAN_APOG)
        longitud = float(res[0][0])
        signo, grado = obtener_signo_grado(longitud)
        casa = obtener_casa(longitud)
        carta['LILITH'] = {
            'signo': signo, 'grado': grado,
            'casa': casa, 'retrogrado': False,
            'longitud': longitud
        }
    except:
        pass

    # Quirón
    try:
        res = swe.calc_ut(jd, swe.CHIRON)
        longitud = float(res[0][0])
        signo, grado = obtener_signo_grado(longitud)
        casa = obtener_casa(longitud)
        carta['QUIRON'] = {
            'signo': signo, 'grado': grado,
            'casa': casa, 'retrogrado': False,
            'longitud': longitud
        }
    except:
        carta['QUIRON'] = {
            'signo': 'N/A', 'grado': 0, 'casa': 0,
            'retrogrado': False, 'longitud': 0
        }

    # Parte de fortuna
    sol_long = carta['SOL']['longitud']
    luna_long = carta['LUNA']['longitud']
    fortuna_long = (ascendente + luna_long - sol_long) % 360
    signo, grado = obtener_signo_grado(fortuna_long)
    casa = obtener_casa(fortuna_long)
    carta['PARTE_FORTUNA'] = {
        'signo': signo, 'grado': grado,
        'casa': casa, 'retrogrado': False,
        'longitud': fortuna_long
    }

    # ASC y MC
    signo_asc, grado_asc = obtener_signo_grado(ascendente)
    carta['ASCENDENTE'] = {
        'signo': signo_asc, 'grado': grado_asc,
        'casa': obtener_casa(ascendente),
        'retrogrado': False, 'longitud': ascendente
    }

    signo_mc, grado_mc = obtener_signo_grado(mc)
    carta['MEDIO_CIELO'] = {
        'signo': signo_mc, 'grado': grado_mc,
        'casa': obtener_casa(mc),
        'retrogrado': False, 'longitud': mc
    }

    # cuspides en signos
    signos_list = [
        "ARIES","TAURO","GEMINIS","CANCER","LEO","VIRGO",
        "LIBRA","ESCORPIO","SAGITARIO","CAPRICORNIO","ACUARIO","PISCIS"
    ]
    cuspides_signos = {}
    for idx, cdeg in enumerate(cuspides, start=1):
        signo_idx = int(cdeg // 30) % 12
        cuspides_signos[str(idx)] = signos_list[signo_idx]

    return {
        "carta": carta,
        "cuspides": cuspides_signos
    }
