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
# ENDPOINT: calcular-transitos (combina natal + cielo + eclipses + fases lunares)
# ---------------------------
@app.post("/calcular-transitos")
def api_calcular_transitos(req: RequestTransitos):
    try:
        print(f"\n{'='*60}")
        print(f"📥 REQUEST: {req.fecha_inicio} → {req.fecha_final}")
        print(f"   Modo: {'NATAL' if not req.incluir_cielo else 'CIELO'}")
        print(f"{'='*60}\n")
        
        # ------------------------------------------------------
        # 1) CALCULAR CARTA NATAL
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
            print(f"✅ Posiciones natales: {len(posiciones_natales)}")

        # ------------------------------------------------------
        # 3) EXTRAER / GENERAR CÚSPIDES (FIX COMPLETO)
        # ------------------------------------------------------
        cuspides = None

        # 3.1 buscar en keys comunes
        if isinstance(carta, dict):
            cuspides_raw = None
            for k in ("cuspides", "cuspides_raw", "cuspides_degrees", "cusps"):
                if k in carta and isinstance(carta[k], list) and len(carta[k]) == 12:
                    cuspides_raw = carta[k]
                    break

            # 3.2 si no vienen explícitas, intentar las alternativas
            if cuspides_raw is None:
                cuspides_raw = carta.get("cuspides_raw") or carta.get("cuspides_degrees")

            # 3.3 si existen, tomar
            if isinstance(cuspides_raw, list) and len(cuspides_raw) == 12:
                cuspides = [float(x) for x in cuspides_raw]
                print(f"✅ Cúspides extraídas: {len(cuspides)}")

            # 3.4 fallback: generar desde transitos.py si nada funcionó
            if cuspides is None:
                try:
                    if hasattr(__import__("transitos"), "calcular_cuspides_desde_natal"):
                        from transitos import calcular_cuspides_desde_natal
                        cuspides_try = calcular_cuspides_desde_natal(
                            req.año_natal, req.mes_natal, req.dia_natal,
                            req.hora_natal, req.minuto_natal,
                            req.latitud_natal, req.longitud_natal,
                            req.sistema
                        )
                        if isinstance(cuspides_try, list) and len(cuspides_try) == 12:
                            cuspides = [float(x) for x in cuspides_try]
                            print(f"✅ Cúspides generadas: {len(cuspides)}")
                except Exception as e:
                    print("⚠️ No se pudieron generar cúspides automáticamente:", str(e))

        if cuspides is None:
            print("❌ NO HAY CÚSPIDES — NO HABRÁ CAMBIOS DE CASA")

        # ------------------------------------------------------
        # 4) CALCULAR TRÁNSITOS
        # ------------------------------------------------------
        print(f"\n🔄 Calculando tránsitos...")

        resultado = calcular_transitos_completo(
            req.fecha_inicio,
            req.fecha_final,
            posiciones_natales=posiciones_natales if posiciones_natales else None,
            cuspides=cuspides,
            incluir_luna=req.incluir_luna,
            incluir_cielo=req.incluir_cielo
        )

        transitos_natal = resultado.get("transitos_natal", [])
        transitos_cielo = resultado.get("transitos_cielo", [])
        eclipses = resultado.get("eclipses", [])
        fases_lunares = resultado.get("fases_lunares", [])

        # ------------------------------------------------------
        # 5) DEBUG RESUMIDO
        # ------------------------------------------------------
        print(f"\n📊 RESULTADOS:")
        print(f"   🌍 Tránsitos natales: {len(transitos_natal)} planetas")
        for t in transitos_natal:
            print(f"      - {t.get('planeta')}: {len(t.get('eventos', []))} eventos")

        print(f"   🌌 Tránsitos cielo: {len(transitos_cielo)} planetas")
        for t in transitos_cielo:
            print(f"      - {t.get('planeta')}: {len(t.get('eventos', []))} eventos")

        print(f"   🌑 Eclipses: {len(eclipses)}")
        print(f"   🌙 Fases Lunares: {len(fases_lunares)}")

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

        print(f"\n📤 Enviando respuesta final…")
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
