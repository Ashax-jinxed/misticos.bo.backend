# =====================================================================
#      ████   BACKEND ASTROLÓGICO COMPLETO — OPTIMIZADO 2026   ████
#          (SIN ELIMINAR NADA — TODO INTACTO Y MEJORADO)
# =====================================================================

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional
import swisseph as swe
import os


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

EPHE_PATH = "ephe"
os.makedirs(EPHE_PATH, exist_ok=True)
swe.set_ephe_path(EPHE_PATH)


# ============================================================
# CONSTELACIONES / ASPECTOS / PLANETAS
# ============================================================

SIGNOS = [
    "Aries","Tauro","Géminis","Cáncer","Leo","Virgo",
    "Libra","Escorpio","Sagitario","Capricornio","Acuario","Piscis"
]

ASPECTOS = {
    "conjuncion":  {"angulo": 0,   "orbe": 8},
    "sextil":      {"angulo": 60,  "orbe": 3},
    "cuadratura":  {"angulo": 90,  "orbe": 6},
    "trigono":     {"angulo": 120, "orbe": 6},
    "oposicion":   {"angulo": 180, "orbe": 8},
}

ASPECTOS_LABEL = {
    "conjuncion": "conjunción",
    "sextil":     "sextil",
    "cuadratura": "cuadratura",
    "trigono":    "trígono",
    "oposicion":  "oposición"
}

PLANETAS = {
    "SOL": swe.SUN,
    "LUNA": swe.MOON,
    "MERCURIO": swe.MERCURY,
    "VENUS": swe.VENUS,
    "MARTE": swe.MARS,
    "JUPITER": swe.JUPITER,
    "SATURNO": swe.SATURN,
    "URANO": swe.URANUS,
    "NEPTUNO": swe.NEPTUNE,
    "PLUTON": swe.PLUTO,
}


# ============================================================
# MODELOS Pydantic
# ============================================================

class RequestTransitos(BaseModel):
    fecha_inicio: str
    fecha_final: str
    año_natal: int
    mes_natal: int
    dia_natal: int
    hora_natal: int
    minuto_natal: int
    latitud_natal: float
    longitud_natal: float
    zona_horaria_natal: float
    sistema: str = "P"

class RequestTransitosCielo(RequestTransitos):
    incluir_luna: bool = True


# ============================================================
# UTILIDADES
# ============================================================

def distancia_aspecto(lon1, lon2):
    diff = abs(lon1 - lon2) % 360
    return diff if diff <= 180 else 360 - diff

def signo(longitud):
    return SIGNOS[int(longitud // 30)]

def calcular_casa(jd, lat, lon, planeta):
    try:
        casas = swe.houses(jd, lat, lon, b"P")[0]
        lon_p = swe.calc_ut(jd, planeta)[0][0] % 360
        for i in range(12):
            if lon_p < casas[i]:
                return i + 1
        return 12
    except:
        return None

def datos_planeta(jd, planeta, lat, lon):
    pos, _ = swe.calc_ut(jd, planeta)
    longitud = pos[0] % 360
    velocidad = pos[3]
    return {
        "longitud": longitud,
        "signo": signo(longitud),
        "grado": longitud % 30,
        "casa": calcular_casa(jd, lat, lon, planeta),
        "retrogrado": velocidad < 0
    }


# ============================================================
# CÁLCULO: TRÁNSITOS VS CARTA NATAL
# ============================================================

def calcular_transitos_natal(req: RequestTransitos):

    # Carta natal
    jd_natal = swe.julday(
        req.año_natal, req.mes_natal, req.dia_natal,
        req.hora_natal + req.minuto_natal / 60 - req.zona_horaria_natal
    )

    pos_natales = {
        p: datos_planeta(jd_natal, PLANETAS[p], req.latitud_natal, req.longitud_natal)
        for p in PLANETAS
    }

    inicio = datetime.strptime(req.fecha_inicio, "%Y-%m-%d")
    final = datetime.strptime(req.fecha_final, "%Y-%m-%d")

    resultados = []

    # Procesar cada planeta
    for planeta, code in PLANETAS.items():
        eventos = []
        estados = {asp: None for asp in ASPECTOS}

        fecha = inicio
        pos_ini = datos_planeta(
            swe.julday(inicio.year, inicio.month, inicio.day, 12),
            code, req.latitud_natal, req.longitud_natal
        )
        pos_fin = datos_planeta(
            swe.julday(final.year, final.month, final.day, 12),
            code, req.latitud_natal, req.longitud_natal
        )

        # Recorrido día por día
        while fecha <= final:
            jd = swe.julday(fecha.year, fecha.month, fecha.day, 12)

            pos_tr = datos_planeta(jd, code, req.latitud_natal, req.longitud_natal)
            pos_nat = pos_natales[planeta]
            fecha_str = fecha.strftime("%Y-%m-%d")

            # CAMBIO DE SIGNO
            jd_ayer = swe.julday(
                (fecha - timedelta(days=1)).year,
                (fecha - timedelta(days=1)).month,
                (fecha - timedelta(days=1)).day,
                12
            )
            signo_ayer = datos_planeta(jd_ayer, code, req.latitud_natal, req.longitud_natal)["signo"]

            if signo_ayer != pos_tr["signo"]:
                eventos.append({
                    "tipo": "cambio_signo",
                    "fecha": fecha_str,
                    "descripcion": f"{planeta} entra en {pos_tr['signo']}"
                })

            # ASPECTOS A NATAL
            for asp, cfg in ASPECTOS.items():
                ang = cfg["angulo"]
                orbe = cfg["orbe"]

                diff = distancia_aspecto(
                    (pos_tr["longitud"] - pos_nat["longitud"]) % 360, ang
                )

                activo = estados[asp]

                if diff <= orbe and activo is None:
                    estados[asp] = {
                        "inicio": fecha_str,
                        "exacto": fecha_str,
                        "dist_min": diff
                    }

                elif diff <= orbe and activo:
                    if diff < activo["dist_min"]:
                        activo["dist_min"] = diff
                        activo["exacto"] = fecha_str

                elif diff > orbe and activo:
                    eventos.append({
                        "tipo": "aspecto",
                        "aspecto": asp,
                        "fecha_inicio": activo["inicio"],
                        "fecha_exacto": activo["exacto"],
                        "fecha_fin": fecha_str,
                        "descripcion": f"{planeta} {ASPECTOS_LABEL[asp]} Natal"
                    })
                    estados[asp] = None

            fecha += timedelta(days=1)

        resultados.append({
            "planeta": planeta,
            "posicion_inicial": pos_ini,
            "posicion_final": pos_fin,
            "eventos": eventos
        })

    return resultados


# ============================================================
# CÁLCULO: TRÁNSITOS VS TRÁNSITOS (CLIMA DEL CIELO)
# ============================================================

def calcular_transitos_cielo(req: RequestTransitosCielo):

    planetas_dict = PLANETAS.copy()
    if not req.incluir_luna:
        del planetas_dict["LUNA"]

    nombres = list(planetas_dict.keys())

    resultados = {p: {"planeta": p, "eventos": []} for p in nombres}

    estados = {}

    inicio = datetime.strptime(req.fecha_inicio, "%Y-%m-%d")
    final = datetime.strptime(req.fecha_final, "%Y-%m-%d")

    fecha = inicio
    while fecha <= final:

        jd = swe.julday(fecha.year, fecha.month, fecha.day, 12)
        fecha_str = fecha.strftime("%Y-%m-%d")

        longitudes = {
            p: swe.calc_ut(jd, planetas_dict[p])[0][0] % 360
            for p in nombres
        }

        for i in range(len(nombres)):
            for j in range(i + 1, len(nombres)):
                p1, p2 = nombres[i], nombres[j]

                diff = (longitudes[p1] - longitudes[p2]) % 360

                for asp, cfg in ASPECTOS.items():
                    ang = cfg["angulo"]
                    orbe = cfg["orbe"]

                    d = distancia_aspecto(diff, ang)
                    key = f"{p1}_{p2}_{asp}"

                    activo = estados.get(key)

                    # entrar
                    if d <= orbe and activo is None:
                        estados[key] = {
                            "inicio": fecha_str,
                            "exacto": fecha_str,
                            "dist_min": d
                        }

                    # mejor exactitud
                    elif d <= orbe and activo:
                        if d < activo["dist_min"]:
                            activo["dist_min"] = d
                            activo["exacto"] = fecha_str

                    # salir
                    elif d > orbe and activo:
                        est = estados[key]
                        evento = {
                            "tipo": "aspecto_transito",
                            "planeta1": p1,
                            "planeta2": p2,
                            "aspecto": asp,
                            "fecha_inicio": est["inicio"],
                            "fecha_exacto": est["exacto"],
                            "fecha_fin": fecha_str,
                            "descripcion": f"{p1} {ASPECTOS_LABEL[asp]} {p2}"
                        }
                        resultados[p1]["eventos"].append(evento)
                        resultados[p2]["eventos"].append(evento)
                        del estados[key]

        fecha += timedelta(days=1)

    return list(resultados.values())


# ============================================================
# ENDPOINTS
# ============================================================

@app.post("/calcular-transitos")
def api_transitos(req: RequestTransitos):
    try:
        return {
            "periodo": {"inicio": req.fecha_inicio, "fin": req.fecha_final},
            "transitos": calcular_transitos_natal(req)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/calcular-transitos-cielo")
def api_cielo(req: RequestTransitosCielo):
    try:
        return {
            "periodo": {"inicio": req.fecha_inicio, "fin": req.fecha_final},
            "incluir_luna": req.incluir_luna,
            "transitos": calcular_transitos_cielo(req)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def root():
    return {"status": "OK", "message": "Backend operativo."}
