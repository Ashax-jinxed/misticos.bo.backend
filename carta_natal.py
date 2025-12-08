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
    
    # 🐛 DEBUG - Imprime valores de ASC y MC
    print(f"\n🐛 DEBUG ASC: {ascendente:.4f}° = {obtener_signo_grado(ascendente)[0]} {obtener_signo_grado(ascendente)[1]:.2f}°")
    print(f"🐛 DEBUG MC: {mc:.4f}° = {obtener_signo_grado(mc)[0]} {obtener_signo_grado(mc)[1]:.2f}°")
    print(f"🐛 DEBUG Cúspide Casa 10: {cuspides_placidus[9]:.4f}° = {obtener_signo_grado(cuspides_placidus[9])[0]} {obtener_signo_grado(cuspides_placidus[9])[1]:.2f}°")
    print(f"🐛 MC == Cúspide 10? {abs(mc - cuspides_placidus[9]) < 0.01}")
    
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

    # Nodo norte y sur - CORREGIDO con flags
    try:
        res = swe.calc_ut(jd, swe.TRUE_NODE, swe.FLG_SWIEPH)
        longitud = float(res[0][0])
        signo, grado = obtener_signo_grado(longitud)
        casa = obtener_casa(longitud)
        
        # 🐛 DEBUG - Nodo Norte
        print(f"🐛 DEBUG Nodo Norte: {longitud:.4f}° = {signo} {grado:.2f}° → Casa {casa}")
        
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

    # Lilith - CORREGIDO usar True Black Moon (osculating)
    try:
        res = swe.calc_ut(jd, swe.OSCU_APOG, swe.FLG_SWIEPH)
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
        res = swe.calc_ut(jd, swe.CHIRON, swe.FLG_SWIEPH)
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

    # Parte de fortuna - CORREGIDO con fórmula día/noche
    sol_long = carta['SOL']['longitud']
    luna_long = carta['LUNA']['longitud']
    
    # Determinar si es carta diurna (Sol sobre horizonte = casas 7-12)
    es_diurna = carta['SOL']['casa'] >= 7
    
    if es_diurna:
        # Fórmula diurna: ASC + Luna - Sol
        fortuna_long = (ascendente + luna_long - sol_long) % 360
    else:
        # Fórmula nocturna: ASC + Sol - Luna
        fortuna_long = (ascendente + sol_long - luna_long) % 360
    
    signo, grado = obtener_signo_grado(fortuna_long)
    casa = obtener_casa(fortuna_long)
    
    # 🐛 DEBUG - Parte de Fortuna
    print(f"🐛 DEBUG Parte Fortuna: {fortuna_long:.4f}° = {signo} {grado:.2f}° → Casa {casa}")
    print(f"🐛 Es diurna? {es_diurna} (Sol en casa {carta['SOL']['casa']})")
    
    carta['PARTE_FORTUNA'] = {
        'signo': signo, 'grado': grado,
        'casa': casa, 'retrogrado': False,
        'longitud': fortuna_long
    }

    # ASC y MC
    signo_asc, grado_asc = obtener_signo_grado(ascendente)
    carta['ASCENDENTE'] = {
        'signo': signo_asc, 'grado': grado_asc,
        'casa': 1,  # ASC siempre es casa 1
        'retrogrado': False, 'longitud': ascendente
    }

    signo_mc, grado_mc = obtener_signo_grado(mc)
    carta['MEDIO_CIELO'] = {
        'signo': signo_mc, 'grado': grado_mc,
        'casa': 10,  # MC siempre es casa 10
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

    # 🐛 DEBUG - Imprime todas las cúspides
    print("\n🏠 CÚSPIDES PLACIDUS:")
    for i, cusp in enumerate(cuspides, start=1):
        signo_c, grado_c = obtener_signo_grado(cusp)
        print(f"Casa {i}: {signo_c} {grado_c:.2f}° ({cusp:.2f}°)")
    print()

    return {
        "carta": carta,
        "cuspides": cuspides_signos
    }