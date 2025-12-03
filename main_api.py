# main_api.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal, Dict, Any
from pathlib import Path
import os
import swisseph as swe

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

# ---------------------------
# ENDPOINT: calcular-carta
# ---------------------------
@app.post("/calcular-carta")
def api_calcular_carta(req: RequestCarta):
    try:
        resultado = calcular_carta_natal(
            req.año, req.mes, req.dia, req.hora, req.minuto,
            req.latitud, req.longitud, req.zona_horaria,
            sistema_casas=req.sistema
        )
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------
# ENDPOINT: calcular-transitos (combina natal + cielo)
# ---------------------------
@app.post("/calcular-transitos")
def api_calcular_transitos(req: RequestTransitos):
    try:
        # 1) calcular carta natal (obligatorio para tránsitos natales)
        carta = calcular_carta_natal(
            req.año_natal, req.mes_natal, req.dia_natal, req.hora_natal, req.minuto_natal,
            req.latitud_natal, req.longitud_natal, req.zona_horaria_natal,
            sistema_casas=req.sistema
        )

        # 2) extraer posiciones natales y cuspides
        posiciones_natales = {}
        cuspides = None
        if isinstance(carta, dict) and "carta" in carta:
            for nombre, info in carta["carta"].items():
                if isinstance(info, dict) and "longitud" in info:
                    posiciones_natales[nombre] = float(info["longitud"])
        if isinstance(carta, dict) and "cuspides" in carta:
            # cuspides como signos actuales; transitos.py necesita grados eclípticos (si los tenés en carta_natal, pásalos)
            # Aquí asumimos que carta_natal devolvió 'cuspides' como dict idx->signo; si tienes cúspides grados,
            # reemplaza esta línea por la lista de 12 grados.
            try:
                # If carta_natal provided numeric cuspides, use them
                cuspides_raw = carta.get("cuspides_raw") or carta.get("cuspides_degrees")
                if isinstance(cuspides_raw, list) and len(cuspides_raw) == 12:
                    cuspides = cuspides_raw
            except Exception:
                cuspides = None

        # 3) llamar motor de tránsitos (devuelve ambos conjuntos según parámetros)
        resultado = calcular_transitos_completo(
            req.fecha_inicio,
            req.fecha_final,
            posiciones_natales=posiciones_natales if posiciones_natales else None,
            cuspides=cuspides,
            incluir_luna=req.incluir_luna,
            incluir_cielo=req.incluir_cielo
        )

        # 4) envolver con metadatos básicos
        return {
            "periodo": {"inicio": req.fecha_inicio, "fin": req.fecha_final},
            "natal": {
                "fecha": f"{req.año_natal}-{req.mes_natal}-{req.dia_natal}",
                "hora": f"{req.hora_natal}:{req.minuto_natal}",
                "ubicacion": {"lat": req.latitud_natal, "lon": req.longitud_natal}
            },
            "transitos_natal": resultado.get("transitos_natal", []),
            "transitos_cielo": resultado.get("transitos_cielo", [])
        }

    except Exception as e:
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
# Agrega este endpoint después de @app.post("/calcular-carta")
# y antes de @app.post("/calcular-transitos")

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
