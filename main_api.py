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
    
# AGREGAR ESTO AL ARCHIVO main_api.py (después de la clase RequestCarta)

from datetime import datetime, timedelta

class RequestTransitos(BaseModel):
    fecha_inicio: str  # formato "YYYY-MM-DD"
    fecha_final: str   # formato "YYYY-MM-DD"
    año_natal: int
    mes_natal: int
    dia_natal: int
    hora_natal: int
    minuto_natal: int
    latitud_natal: float
    longitud_natal: float
    zona_horaria_natal: int
    sistema: Literal['P', 'W'] = 'P'


def calcular_transitos_planeta(planeta_num, nombre_planeta, fecha_inicio, fecha_final, 
                                año_natal, mes_natal, dia_natal, hora_natal, minuto_natal,
                                latitud_natal, longitud_natal, zona_horaria_natal, sistema_casas='P'):
    """
    Calcula todos los tránsitos de un planeta entre dos fechas.
    Retorna lista de eventos: cambios de signo, casa y retrogradaciones.
    """
    swe.set_ephe_path(EPHE_PATH)
    
    # Calcular carta natal para obtener las cúspides
    hora_utc_natal = hora_natal - zona_horaria_natal
    dia_utc_natal = dia_natal
    if hora_utc_natal >= 24:
        hora_utc_natal -= 24
        dia_utc_natal += 1
    elif hora_utc_natal < 0:
        hora_utc_natal += 24
        dia_utc_natal -= 1
    
    jd_natal = swe.julday(año_natal, mes_natal, dia_utc_natal, hora_utc_natal + minuto_natal/60.0)
    casas_data = swe.houses(jd_natal, latitud_natal, longitud_natal, sistema_casas.encode())
    cuspides_placidus = list(casas_data[0][:12])
    ascendente = casas_data[1][0]
    signo_ascendente = int(ascendente // 30) % 12
    
    # Configurar función de casas
    if sistema_casas == 'W':
        cuspides = [(signo_ascendente * 30 + i * 30) % 360 for i in range(12)]
        def obtener_casa(long_ec):
            signo_punto = int(long_ec // 30) % 12
            diferencia = (signo_punto - signo_ascendente) % 12
            return diferencia + 1
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
    
    eventos = []
    
    # Parsear fechas
    f_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    f_final = datetime.strptime(fecha_final, "%Y-%m-%d")
    
    # Determinar incremento según el planeta (Luna: cada 12h, planetas rápidos: cada día, lentos: cada 3 días)
    if nombre_planeta == "LUNA":
        delta = timedelta(hours=12)
    elif nombre_planeta in ["SOL", "MERCURIO", "VENUS", "MARTE"]:
        delta = timedelta(days=1)
    else:
        delta = timedelta(days=3)
    
    fecha_actual = f_inicio
    signo_anterior = None
    casa_anterior = None
    retrogrado_anterior = None
    
    while fecha_actual <= f_final:
        jd = swe.julday(fecha_actual.year, fecha_actual.month, fecha_actual.day, 12.0)
        
        try:
            res = swe.calc_ut(jd, planeta_num, swe.FLG_SWIEPH | swe.FLG_SPEED)
            longitud = float(res[0][0])
            velocidad = float(res[0][3])
            
            signo_actual = int(longitud // 30) % 12
            casa_actual = obtener_casa(longitud)
            retrogrado_actual = velocidad < 0
            
            # Detectar cambio de signo
            if signo_anterior is not None and signo_actual != signo_anterior:
                signos = ["ARIES","TAURO","GEMINIS","CANCER","LEO","VIRGO",
                         "LIBRA","ESCORPIO","SAGITARIO","CAPRICORNIO","ACUARIO","PISCIS"]
                eventos.append({
                    "tipo": "cambio_signo",
                    "fecha": fecha_actual.strftime("%Y-%m-%d"),
                    "signo_anterior": signos[signo_anterior],
                    "signo_nuevo": signos[signo_actual],
                    "descripcion": f"Ingresa a {signos[signo_actual]}"
                })
            
            # Detectar cambio de casa
            if casa_anterior is not None and casa_actual != casa_anterior:
                eventos.append({
                    "tipo": "cambio_casa",
                    "fecha": fecha_actual.strftime("%Y-%m-%d"),
                    "casa_anterior": casa_anterior,
                    "casa_nueva": casa_actual,
                    "descripcion": f"Ingresa a casa {casa_actual}"
                })
            
            # Detectar cambio de retrogradación
            if retrogrado_anterior is not None and retrogrado_actual != retrogrado_anterior:
                if retrogrado_actual:
                    eventos.append({
                        "tipo": "retrogrado_inicio",
                        "fecha": fecha_actual.strftime("%Y-%m-%d"),
                        "descripcion": "Inicia retrogradación"
                    })
                else:
                    eventos.append({
                        "tipo": "retrogrado_fin",
                        "fecha": fecha_actual.strftime("%Y-%m-%d"),
                        "descripcion": "Termina retrogradación (directo)"
                    })
            
            signo_anterior = signo_actual
            casa_anterior = casa_actual
            retrogrado_anterior = retrogrado_actual
            
        except Exception as e:
            print(f"Error calculando {nombre_planeta} en {fecha_actual}: {e}")
        
        fecha_actual += delta
    
    # Información inicial y final
    jd_inicio = swe.julday(f_inicio.year, f_inicio.month, f_inicio.day, 12.0)
    jd_final = swe.julday(f_final.year, f_final.month, f_final.day, 12.0)
    
    try:
        res_inicio = swe.calc_ut(jd_inicio, planeta_num, swe.FLG_SWIEPH | swe.FLG_SPEED)
        long_inicio = float(res_inicio[0][0])
        vel_inicio = float(res_inicio[0][3])
        signo_inicio = int(long_inicio // 30) % 12
        casa_inicio = obtener_casa(long_inicio)
        
        res_final = swe.calc_ut(jd_final, planeta_num, swe.FLG_SWIEPH | swe.FLG_SPEED)
        long_final = float(res_final[0][0])
        vel_final = float(res_final[0][3])
        signo_final = int(long_final // 30) % 12
        casa_final = obtener_casa(long_final)
        
        signos = ["ARIES","TAURO","GEMINIS","CANCER","LEO","VIRGO",
                 "LIBRA","ESCORPIO","SAGITARIO","CAPRICORNIO","ACUARIO","PISCIS"]
        
        posicion_inicial = {
            "signo": signos[signo_inicio],
            "casa": casa_inicio,
            "grado": float(long_inicio % 30),
            "retrogrado": vel_inicio < 0
        }
        
        posicion_final = {
            "signo": signos[signo_final],
            "casa": casa_final,
            "grado": float(long_final % 30),
            "retrogrado": vel_final < 0
        }
        
    except Exception as e:
        print(f"Error calculando posiciones inicial/final de {nombre_planeta}: {e}")
        posicion_inicial = None
        posicion_final = None
    
    return {
        "planeta": nombre_planeta,
        "posicion_inicial": posicion_inicial,
        "posicion_final": posicion_final,
        "eventos": eventos
    }


@app.post("/calcular-transitos")
def api_calcular_transitos(req: RequestTransitos):
    print(f"\n{'=' * 50}")
    print(f"🔮 Calculando tránsitos:")
    print(f"   Período: {req.fecha_inicio} a {req.fecha_final}")
    print(f"   Natal: {req.año_natal}-{req.mes_natal}-{req.dia_natal} {req.hora_natal}:{req.minuto_natal}")
    print(f"   Ubicación: Lat {req.latitud_natal}, Lon {req.longitud_natal}")
    print(f"   Sistema: {req.sistema}")
    print(f"{'=' * 50}")
    
    try:
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
            'PLUTON': swe.PLUTO,
            'NODO_NORTE': swe.TRUE_NODE,
            'LILITH': swe.MEAN_APOG,
            'QUIRON': swe.CHIRON
        }
        
        resultados = []
        
        for nombre, num in planetas.items():
            print(f"📍 Calculando {nombre}...")
            resultado = calcular_transitos_planeta(
                num, nombre,
                req.fecha_inicio, req.fecha_final,
                req.año_natal, req.mes_natal, req.dia_natal,
                req.hora_natal, req.minuto_natal,
                req.latitud_natal, req.longitud_natal,
                req.zona_horaria_natal,
                sistema_casas=req.sistema
            )
            resultados.append(resultado)
        
        print("✅ Tránsitos calculados exitosamente")
        print(f"{'=' * 50}\n")
        
        return {
            "periodo": {
                "inicio": req.fecha_inicio,
                "fin": req.fecha_final
            },
            "natal": {
                "fecha": f"{req.año_natal}-{req.mes_natal}-{req.dia_natal}",
                "hora": f"{req.hora_natal}:{req.minuto_natal}",
                "ubicacion": {"lat": req.latitud_natal, "lon": req.longitud_natal}
            },
            "transitos": resultados
        }
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        print(f"{'=' * 50}\n")
        raise HTTPException(status_code=500, detail=str(e))

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