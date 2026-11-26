# main_api.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal, Dict, Any
from pathlib import Path
from astro_seek_scraper import obtener_url_imagen_carta
import os
import swisseph as swe

DEBUG = os.getenv("ASTRO_DEBUG", "0") == "1"


def _dbg(*args):
    if DEBUG:
        print(*args)

# Importa módulos locales
from carta_natal import calcular_carta_natal_sola as calcular_carta_natal
from transitos import calcular_transitos_completo

# EPHE path
BASE_DIR = Path(__file__).resolve().parent
EPHE_PATH = str(BASE_DIR / "ephe")
os.makedirs(EPHE_PATH, exist_ok=True)
swe.set_ephe_path(EPHE_PATH)

app = FastAPI(title="API Carta+Tránsitos - A1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    swe.set_ephe_path(EPHE_PATH)
    print(f"[startup] SwissEphem path: {EPHE_PATH}")

# ---------------------------
# MODELS
# ---------------------------
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

class RequestImagenCarta(BaseModel):
    url_astroseek: str    

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
    zona_horaria_natal: int
    sistema: Literal['P', 'W'] = 'P'
    incluir_cielo: bool = True
    incluir_luna: bool = True

class RequestAspectos(BaseModel):
    año: int
    mes: int
    dia: int
    hora: int = 12
    minuto: int = Field(0, ge=0, le=59)
    latitud: float
    longitud: float
    zona_horaria: int
    sistema: Literal['P', 'W'] = 'P'
    
@app.post("/calcular-transitos")
def api_calcular_transitos(req: RequestTransitos):
    try:
        _dbg(f"🔥 REQUEST: {req.fecha_inicio} → {req.fecha_final} | sistema {req.sistema}")
        
        # ------------------------------------------------------
        # 1) CALCULAR CARTA NATAL (solo para posiciones)
        # ------------------------------------------------------
        carta = calcular_carta_natal(
            req.año_natal, req.mes_natal, req.dia_natal,
            req.hora_natal, req.minuto_natal,
            req.latitud_natal, req.longitud_natal,
            req.zona_horaria_natal,
            sistema_casas=req.sistema
        )

        # ------------------------------------------------------
        # 2) EXTRAER POSICIONES NATIVAS
        # ------------------------------------------------------
        posiciones_natales = {}
        if isinstance(carta, dict) and "carta" in carta:
            for nombre, info in carta["carta"].items():
                if isinstance(info, dict) and "longitud" in info:
                    posiciones_natales[nombre] = float(info["longitud"])
            _dbg(f"✅ Posiciones natales: {len(posiciones_natales)}")

        # ------------------------------------------------------
        # 3) CALCULAR TRÁNSITOS (sin pasar cúspides - las calcula internamente)
        # ------------------------------------------------------

        resultado = calcular_transitos_completo(
            req.fecha_inicio,
            req.fecha_final,
            posiciones_natales=posiciones_natales if posiciones_natales else None,
            cuspides=None,  # ← Ya no pasamos cúspides
            incluir_luna=req.incluir_luna,
            incluir_cielo=req.incluir_cielo,
            sistema=req.sistema,
            # ⬇️ PASAR DATOS NATALES:
            año_natal=req.año_natal,
            mes_natal=req.mes_natal,
            dia_natal=req.dia_natal,
            hora_natal=req.hora_natal,
            minuto_natal=req.minuto_natal,
            latitud_natal=req.latitud_natal,
            longitud_natal=req.longitud_natal,
            zona_horaria_natal=req.zona_horaria_natal
        )    

        transitos_natal = resultado.get("transitos_natal", [])
        transitos_cielo = resultado.get("transitos_cielo", [])
        eclipses = resultado.get("eclipses", [])
        fases_lunares = resultado.get("fases_lunares", [])

        if DEBUG:
            print(f"📊 natal={len(transitos_natal)} cielo={len(transitos_cielo)} "
                  f"eclipses={len(eclipses)} fases={len(fases_lunares)}")

        # ------------------------------------------------------
        # 6) RESPUESTA
        # ------------------------------------------------------
        respuesta = {
            "periodo": {"inicio": req.fecha_inicio, "fin": req.fecha_final},
            "natal": {
                "fecha": f"{req.año_natal}-{req.mes_natal:02d}-{req.dia_natal:02d}",
                "hora": f"{req.hora_natal:02d}:{req.minuto_natal:02d}",
                "ubicacion": {"lat": req.latitud_natal, "lon": req.longitud_natal}
            },
            "transitos_natal": transitos_natal,
            "transitos_cielo": transitos_cielo,
            "eclipses": eclipses,
            "fases_lunares": fases_lunares
        }

        return respuesta

    except Exception as e:
        print(f"\n❌ ERROR en /calcular-transitos: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------
# health & root
# ---------------------------
@app.get("/health")
def health():
    return {"status": "ok", "ephe_path": EPHE_PATH, "ephe_exists": os.path.exists(EPHE_PATH)}

@app.get("/")
def root():
    return {"status": "ok", "message": "API operativa"}

@app.post("/carta-natal-sola")
def api_carta_natal_sola(req: RequestCarta):
    """
    Endpoint alternativo para calcular carta natal.
    Mantiene compatibilidad con clientes que usen esta ruta.
    """
    try:
        resultado = calcular_carta_natal(
            req.año, req.mes, req.dia, req.hora, req.minuto,
            req.latitud, req.longitud, req.zona_horaria,
            sistema_casas=req.sistema
        )
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/imagen-carta-astroseek")
def api_imagen_carta_astroseek(req: RequestImagenCarta):
    """
    Recibe la URL de cálculo de astro-seek ya generada por el frontend,
    consulta esa página y devuelve la URL de la imagen de la rueda astrológica.
    """
    try:
        url_imagen = obtener_url_imagen_carta(req.url_astroseek)
        return {"url_imagen": url_imagen}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    
_ASPECTOS_NATALES = (
    ("conjunción", 0.0),
    ("sextil", 60.0),
    ("cuadratura", 90.0),
    ("trígono", 120.0),
    ("oposición", 180.0),
)

_PLANETAS_ASPECTOS = ('SOL', 'LUNA', 'MERCURIO', 'VENUS', 'MARTE',
                      'JUPITER', 'SATURNO', 'URANO', 'NEPTUNO', 'PLUTON',
                      'NODO_NORTE', 'ASCENDENTE', 'MEDIO_CIELO')


def calcular_aspectos_natales(carta: Dict[str, Any], orbe_max: float = 5.0):
    """
    Calcula aspectos entre planetas natales con orbe <= orbe_max
    """
    presentes = [(p, carta[p].get('longitud', 0)) for p in _PLANETAS_ASPECTOS if p in carta]
    aspectos_encontrados = []

    for i, (p1, lon1) in enumerate(presentes):
        for p2, lon2 in presentes[i + 1:]:
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff

            for nombre_aspecto, angulo_objetivo in _ASPECTOS_NATALES:
                distancia = abs(diff - angulo_objetivo)
                if distancia <= orbe_max:
                    orbe_r = round(distancia, 2)
                    aspectos_encontrados.append({
                        "planeta1": p1,
                        "planeta2": p2,
                        "aspecto": nombre_aspecto,
                        "orbe": orbe_r,
                        "descripcion": f"{p1} {nombre_aspecto} {p2} (orbe {orbe_r}°)"
                    })

    # Ordenar por orbe (más exactos primero)
    aspectos_encontrados.sort(key=lambda x: x['orbe'])
    return aspectos_encontrados

@app.post("/aspectos-natales")
def api_aspectos_natales(req: RequestAspectos):
    """
    Calcula aspectos natales con orbe <= 5°
    """
    try:
        # Calcular carta natal
        resultado = calcular_carta_natal(
            req.año, req.mes, req.dia, req.hora, req.minuto,
            req.latitud, req.longitud, req.zona_horaria,
            sistema_casas=req.sistema
        )
        
        # Extraer carta
        carta = resultado.get('carta', {})
        
        # Calcular aspectos
        aspectos = calcular_aspectos_natales(carta, orbe_max=5.0)
        
        _dbg(f"✅ Aspectos calculados: {len(aspectos)}")
        
        return {
            "aspectos": aspectos,
            "total": len(aspectos)
        }
        
    except Exception as e:
        print(f"❌ ERROR en /aspectos-natales: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/debug-quiron")
def debug_quiron():
    from swe_lock import SWE_LOCK
    info = {"ephe_path": EPHE_PATH, "archivos": {}}
    for f in ("seas_18.se1", "semo_18.se1", "sepl_18.se1"):
        p = os.path.join(EPHE_PATH, f)
        info["archivos"][f] = os.path.getsize(p) if os.path.exists(p) else "FALTA"
    jd = swe.julday(1990, 1, 1, 12.0)
    with SWE_LOCK:
        try:
            xx, ret = swe.calc_ut(jd, swe.CHIRON, swe.FLG_SWIEPH | swe.FLG_SPEED)
            info["retflag"] = ret
            info["longitud"] = float(xx[0])
        except Exception as e:
            info["error"] = repr(e)
    return info    