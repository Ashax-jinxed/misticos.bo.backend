# main_api.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal
import swisseph as swe
import os
from pathlib import Path

# Ruta de efemérides compatible con Render (Linux) y local (Windows)
BASE_DIR = Path(__file__).resolve().parent
EPHE_PATH = str(BASE_DIR / "ephe")

# --- FastAPI app ---
app = FastAPI(title="API Carta Natal - Render")

# Configuración de CORS (una sola vez)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción puedes especificar tu dominio de Netlify
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurar Swiss Ephemeris en el arranque de la app
@app.on_event("startup")
def inicializar_swisseph():
    if not os.path.exists(EPHE_PATH):
        print(f"⚠️ ADVERTENCIA: La carpeta de efemérides no existe en: {EPHE_PATH}")
        print("   Creando carpeta...")
        os.makedirs(EPHE_PATH, exist_ok=True)
    
    swe.set_ephe_path(EPHE_PATH)
    print(f"✅ [SwissEphem] Ruta de efemérides configurada en: {EPHE_PATH}")


def obtener_signo_grado(longitud_ec):
    signos = [
        "ARIES","TAURO","GEMINIS","CANCER","LEO","VIRGO",
        "LIBRA","ESCORPIO","SAGITARIO","CAPRICORNIO","ACUARIO","PISCIS"
    ]
    signo_index = int(longitud_ec // 30) % 12
    grado = (longitud_ec % 30)
    return signos[signo_index], grado


def calcular_carta_natal(año, mes, dia, hora, minuto, latitud, longitud, zona_horaria, sistema_casas='P'):
    # Configurar ruta de efemérides
    swe.set_ephe_path(EPHE_PATH)

    # convierte hora local a UTC y obtiene JD
    hora_utc = hora - zona_horaria
    dia_utc = dia
    if hora_utc >= 24:
        hora_utc -= 24
        dia_utc += 1
    elif hora_utc < 0:
        hora_utc += 24
        dia_utc -= 1

    jd = swe.julday(año, mes, dia_utc, hora_utc + minuto/60.0)

    # calcular casas (Placidus para obtener ASC/MC)
    casas_data = swe.houses(jd, latitud, longitud, b'P')
    cuspides_placidus = list(casas_data[0][:12])
    ascendente = casas_data[1][0]
    mc = casas_data[1][1]
    signo_ascendente = int(ascendente // 30) % 12

    # configurar cúspides según sistema
    if sistema_casas == 'W':
        cuspides = [(signo_ascendente * 30 + i * 30) % 360 for i in range(12)]

        def obtener_casa_whole(long_ec):
            signo_punto = int(long_ec // 30) % 12
            diferencia = (signo_punto - signo_ascendente) % 12
            return diferencia + 1

        obtener_casa = obtener_casa_whole
    else:
        cuspides = cuspides_placidus

        def obtener_casa_placidus(long_ec):
            # compara con cúspides (en grados eclípticos)
            # normaliza para el cruce de 0°
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

        obtener_casa = obtener_casa_placidus

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
            'retrogrado': bool(velocidad < 0),
            'longitud': float(longitud)
        }

    # NODO NORTE (TRUE_NODE)
    try:
        res = swe.calc_ut(jd, swe.TRUE_NODE, swe.FLG_SWIEPH)
        longitud = float(res[0][0])
        signo, grado = obtener_signo_grado(longitud)
        casa = obtener_casa(longitud)
        carta['NODO_NORTE'] = {
            'signo': signo,
            'grado': float(grado),
            'casa': int(casa),
            'retrogrado': False,
            'longitud': longitud
        }
        # nodo sur
        longitud_sur = (longitud + 180) % 360
        signo_s, grado_s = obtener_signo_grado(longitud_sur)
        casa_s = obtener_casa(longitud_sur)
        carta['NODO_SUR'] = {
            'signo': signo_s,
            'grado': float(grado_s),
            'casa': int(casa_s),
            'retrogrado': False,
            'longitud': longitud_sur
        }
    except Exception as e:
        print(f"❌ Error calculando Nodo Norte: {e}")

    # LILITH (MEAN_APOG)
    try:
        res = swe.calc_ut(jd, swe.MEAN_APOG, swe.FLG_SWIEPH)
        longitud = float(res[0][0])
        signo, grado = obtener_signo_grado(longitud)
        casa = obtener_casa(longitud)
        carta['LILITH'] = {
            'signo': signo,
            'grado': float(grado),
            'casa': int(casa),
            'retrogrado': False,
            'longitud': longitud
        }
    except Exception as e:
        print(f"❌ Error calculando Lilith: {e}")

    # QUIRÓN - Método mejorado
    quiron_calculado = False
    print("🔍 Iniciando cálculo de Quirón...")
    try:
        print("   Intentando método 1: calc_ut simple")
        pos, _ = swe.calc_ut(jd, swe.CHIRON)
        longitud = float(pos[0])
        signo, grado = obtener_signo_grado(longitud)
        casa = obtener_casa(longitud)
        carta['QUIRON'] = {
            'signo': signo,
            'grado': float(grado),
            'casa': int(casa),
            'retrogrado': False,
            'longitud': longitud
        }
        quiron_calculado = True
        print(f"✅ Quirón calculado exitosamente: {signo} {grado:.2f}°")
    except Exception as e:
        print(f"❌ Error calculando Quirón con método principal: {e}")

    if not quiron_calculado:
        print("⚠️ No se pudo calcular Quirón, usando valor por defecto")
        carta['QUIRON'] = {
            'signo': 'N/A',
            'grado': 0.0,
            'casa': 0,
            'retrogrado': False,
            'longitud': 0.0
        }

    # PARTE DE FORTUNA (Asc + Luna - Sol)
    try:
        sol_long = carta['SOL']['longitud']
        luna_long = carta['LUNA']['longitud']
        fortuna_long = (ascendente + luna_long - sol_long) % 360
        signo, grado = obtener_signo_grado(fortuna_long)
        casa = obtener_casa(fortuna_long)
        carta['PARTE_FORTUNA'] = {
            'signo': signo,
            'grado': float(grado),
            'casa': int(casa),
            'retrogrado': False,
            'longitud': fortuna_long
        }
    except Exception as e:
        print(f"❌ Error calculando Parte de Fortuna: {e}")

    # ASC y MC
    signo_asc, grado_asc = obtener_signo_grado(ascendente)
    carta['ASCENDENTE'] = {
        'signo': signo_asc,
        'grado': float(grado_asc),
        'casa': obtener_casa(ascendente),
        'retrogrado': False,
        'longitud': float(ascendente)
    }
    signo_mc, grado_mc = obtener_signo_grado(mc)
    carta['MEDIO_CIELO'] = {
        'signo': signo_mc,
        'grado': float(grado_mc),
        'casa': obtener_casa(mc),
        'retrogrado': False,
        'longitud': float(mc)
    }

    # devolver cúspides
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


class RequestCarta(BaseModel):
    año: int
    mes: int
    dia: int
    hora: int
    minuto: int = Field(0, ge=0, le=59)
    latitud: float
    longitud: float
    zona_horaria: int
    sistema: Literal['P', 'W'] = 'P'


@app.post("/calcular-carta")
def api_calcular_carta(req: RequestCarta):
    print(f"\n{'=' * 50}")
    print(f"📥 Nueva petición recibida:")
    print(f"   Fecha: {req.año}-{req.mes}-{req.dia} {req.hora}:{req.minuto}")
    print(f"   Ubicación: Lat {req.latitud}, Lon {req.longitud}")
    print(f"   Zona horaria: UTC{req.zona_horaria:+d}")
    print(f"   Sistema: {req.sistema}")
    print(f"{'=' * 50}")

    try:
        print("🔄 Iniciando cálculo de carta natal...")
        resultado = calcular_carta_natal(
            req.año, req.mes, req.dia, req.hora, req.minuto,
            req.latitud, req.longitud, req.zona_horaria, sistema_casas=req.sistema
        )
        print("✅ Carta natal calculada exitosamente")
        print(f"{'=' * 50}\n")
        return resultado
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        print(f"{'=' * 50}\n")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ephe_path": EPHE_PATH,
        "ephe_exists": os.path.exists(EPHE_PATH)
    }


@app.get("/")
def root():
    return {
        "message": "API Carta Natal - Render",
        "endpoints": {
            "health": "/health",
            "calcular_carta": "/calcular-carta [POST]"
        }
    }