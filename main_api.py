# main_api.py (completo, integrado con lo que ya tenías)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal, Dict, Any
import swisseph as swe
import os
from pathlib import Path
from datetime import datetime, timedelta
from carta_natal import calcular_carta_natal_sola

# Ruta de efemérides
BASE_DIR = Path(__file__).resolve().parent
EPHE_PATH = str(BASE_DIR / "ephe")

app = FastAPI(title="API Carta Natal - Render")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def inicializar_swisseph():
    if not os.path.exists(EPHE_PATH):
        os.makedirs(EPHE_PATH, exist_ok=True)
    swe.set_ephe_path(EPHE_PATH)
    print(f"[SwissEphem] ephe path: {EPHE_PATH}")

SIGNOS = [
    "ARIES","TAURO","GEMINIS","CANCER","LEO","VIRGO",
    "LIBRA","ESCORPIO","SAGITARIO","CAPRICORNIO","ACUARIO","PISCIS"
]

ASPECTOS = {
    "conjuncion": {"angulo": 0, "orbe": 6},
    "sextil": {"angulo": 60, "orbe": 4},
    "cuadratura": {"angulo": 90, "orbe": 5},
    "trigono": {"angulo": 120, "orbe": 5},
    "oposicion": {"angulo": 180, "orbe": 6},
}
# Orbes más cerrados para evitar spam

ASPECTOS_T = {
    "conjuncion": {"angulo": 0, "orbe": 1},
    "sextil": {"angulo": 60, "orbe": 0.8},
    "cuadratura": {"angulo": 90, "orbe": 1},
    "trigono": {"angulo": 120, "orbe": 1},
    "oposicion": {"angulo": 180, "orbe": 1},
}


CUERPOS_NATALES_RELEVANTES = {
    "SOL","LUNA","MERCURIO","VENUS","MARTE",
    "JUPITER","SATURNO","URANO","NEPTUNO","PLUTON",
    "ASCENDENTE","MEDIO_CIELO","NODO_NORTE","NODO_SUR",
    "LILITH","QUIRON"
}

PLANETAS_RETORNO = {"JUPITER","SATURNO","QUIRON","NODO_NORTE"}

def obtener_signo_grado(longitud_ec: float):
    signo_index = int(longitud_ec // 30) % 12
    grado = (longitud_ec % 30)
    return SIGNOS[signo_index], grado

def calcular_carta_natal(año, mes, dia, hora, minuto, latitud, longitud, zona_horaria, sistema_casas='P'):
    """
    Calcula carta natal y devuelve diccionario con 'carta' (posiciones) y 'cuspides' (grados)
    """
    swe.set_ephe_path(EPHE_PATH)

    hora_utc = hora - zona_horaria
    dia_utc = dia
    if hora_utc >= 24:
        hora_utc -= 24; dia_utc += 1
    elif hora_utc < 0:
        hora_utc += 24; dia_utc -= 1

    jd = swe.julday(año, mes, dia_utc, hora_utc + minuto/60.0)
    # calculamos casas Placidus por defecto para obtener cúspides (luego adaptamos si W)
    casas_data = swe.houses(jd, latitud, longitud, b'P')
    cuspides = list(casas_data[0][:12])
    ascendente = casas_data[1][0]
    mc = casas_data[1][1]
    signo_asc = int(ascendente // 30) % 12

    # para sistema whole signs, las cúspides serán múltiplos de 30 empezando en el asc
    if sistema_casas == 'W':
        cuspides_whole = [(signo_asc * 30 + i*30) % 360 for i in range(12)]
        cuspides_degs = cuspides_whole
    else:
        cuspides_degs = cuspides

    carta = {}
    # planetas principales
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

    # JD ya definido
    for nombre, num in planetas.items():
        res = swe.calc_ut(jd, num, swe.FLG_SWIEPH | swe.FLG_SPEED)
        longitud = float(res[0][0])
        velocidad = float(res[0][3])
        signo, grado = obtener_signo_grado(longitud)
        # casa: calculada comparando con cuspides_degs
        casa = 12
        for i in range(12):
            a = cuspides_degs[i]
            b = cuspides_degs[(i+1)%12]
            long_n = longitud
            b_n = b
            if b < a:
                if long_n < a:
                    long_n = long_n + 360
                b_n = b + 360
            if a <= long_n < b_n:
                casa = i+1
                break
        carta[nombre] = {
            'signo': signo,
            'grado': float(grado),
            'casa': int(casa),
            'retrogrado': bool(velocidad < 0),
            'longitud': float(longitud)
        }

    # nodo y quirón si están disponibles
    try:
        res = swe.calc_ut(jd, swe.TRUE_NODE, swe.FLG_SWIEPH)
        longitud = float(res[0][0])
        signo, grado = obtener_signo_grado(longitud)
        # calcular casa mismo método:
        casa = 12
        for i in range(12):
            a = cuspides_degs[i]
            b = cuspides_degs[(i+1)%12]
            long_n = longitud
            b_n = b
            if b < a:
                if long_n < a:
                    long_n = long_n + 360
                b_n = b + 360
            if a <= long_n < b_n:
                casa = i+1
                break
        carta['NODO_NORTE'] = {'signo': signo, 'grado': float(grado), 'casa': casa, 'retrogrado': False, 'longitud': float(longitud)}
    except Exception:
        pass

    signo_asc, grado_asc = obtener_signo_grado(ascendente)
    carta['ASCENDENTE'] = {'signo': signo_asc, 'grado': float(grado_asc), 'casa': 1, 'retrogrado': False, 'longitud': float(ascendente)}
    signo_mc, grado_mc = obtener_signo_grado(mc)
    carta['MEDIO_CIELO'] = {'signo': signo_mc, 'grado': float(grado_mc), 'casa': 10, 'retrogrado': False, 'longitud': float(mc)}

    cuspides_signos = {}
    for idx, cdeg in enumerate(cuspides_degs, start=1):
        signo_idx = int(cdeg // 30) % 12
        cuspides_signos[str(idx)] = SIGNOS[signo_idx]

    return {"carta": carta, "cuspides": cuspides_signos, "cuspides_degrees": cuspides_degs}

def construir_posiciones_natales(año, mes, dia, hora, minuto, latitud, longitud, zona_horaria, sistema_casas='P') -> Dict[str, Any]:
    datos = calcular_carta_natal(año, mes, dia, hora, minuto, latitud, longitud, zona_horaria, sistema_casas=sistema_casas)
    carta = datos.get("carta", {})
    posiciones = {}
    for nombre, info in carta.items():
        if nombre in CUERPOS_NATALES_RELEVANTES and "longitud" in info:
            posiciones[nombre] = {"longitud": float(info["longitud"]), "casa": int(info.get("casa", 0)), "signo": info.get("signo")}
    return posiciones

def distancia_aspecto(diff_raw: float, angulo_objetivo: float) -> float:
    diff_raw = diff_raw % 360.0
    if angulo_objetivo == 0:
        return min(diff_raw, 360.0 - diff_raw)
    if angulo_objetivo == 180:
        return abs(diff_raw - 180.0)
    return min(abs(diff_raw - angulo_objetivo), abs(diff_raw - (360.0 - angulo_objetivo)))

def encontrar_momento_aspecto(jd1: float, jd2: float, planeta_num: int, natal_long: float, angulo_objetivo: float):
    for _ in range(22):
        mid = (jd1 + jd2) / 2.0
        lon_mid = swe.calc_ut(mid, planeta_num, swe.FLG_SWIEPH | swe.FLG_SPEED)[0][0]
        diff = (lon_mid - natal_long) % 360.0
        d = distancia_aspecto(diff, angulo_objetivo)
        # simple: ajustamos los extremos
        if d < 0.001:
            return mid, lon_mid
        # aproximación binaria: determinamos hacia donde mover
        # (no implementamos full monotonic check por simplicidad)
        jd1 = mid
    return mid, lon_mid

# detectar eclipses (simple): busca lunaciones (new/full) cerca del nodo
def detectar_eclipses(fecha_inicio: str, fecha_final: str, año_natal:int, mes_natal:int, dia_natal:int, hora_natal:int, minuto_natal:int, lat_natal:float, lon_natal:float, zona_horaria:int, sistema='P'):
    f_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    f_final = datetime.strptime(fecha_final, "%Y-%m-%d")
    # calculamos cúspides natales en grados para determinar casas natales
    datos_natal = calcular_carta_natal(año_natal, mes_natal, dia_natal, hora_natal, minuto_natal, lat_natal, lon_natal, zona_horaria, sistema_casas=sistema)
    cuspides_degs = datos_natal.get("cuspides_degrees", [])
    signo_asc = datos_natal["carta"]["ASCENDENTE"]["longitud"] if "ASCENDENTE" in datos_natal["carta"] else None

    eventos = []
    fecha = f_inicio
    # tolerancias: qué consideramos "luna nueva/llena" y "cerca del nodo"
    lunacion_tol = 5.0  # grados para considerar luna nueva/llena (basta para detectar día)
    nodo_tol = 12.0     # distancia al nodo para considerar eclipse posible

    while fecha <= f_final:
        # usamos mediodía UTC para cada día (suficiente para detectar el día)
        jd = swe.julday(fecha.year, fecha.month, fecha.day, 12.0)
        sol_lon = float(swe.calc_ut(jd, swe.SUN)[0][0]) % 360.0
        luna_lon = float(swe.calc_ut(jd, swe.MOON)[0][0]) % 360.0
        node_lon = float(swe.calc_ut(jd, swe.TRUE_NODE)[0][0]) % 360.0

        diff_sl = (luna_lon - sol_lon) % 360.0  # 0 = new, 180 = full
        diff_node_sol = min(abs((sol_lon - node_lon + 180) % 360 - 180), 360)

        # eclipse solar (new moon near node)
        if min(diff_sl, 360 - diff_sl) < lunacion_tol and diff_node_sol < nodo_tol:
            signo, grado = obtener_signo_grado(sol_lon)
            # calcular casa respecto a cuspides natales
            casa = 12
            for i in range(12):
                a = cuspides_degs[i]
                b = cuspides_degs[(i+1)%12]
                long_n = sol_lon
                b_n = b
                if b < a:
                    if long_n < a:
                        long_n = long_n + 360
                    b_n = b + 360
                if a <= long_n < b_n:
                    casa = i+1
                    break
            eventos.append({
                "tipo": "eclipse",
                "subtipo": "solar",
                "fecha": fecha.strftime("%Y-%m-%d"),
                "descripcion": f"Eclipse solar (Luna nueva cerca del nodo) - Cae en {signo} · Casa {casa}",
                "signo": signo,
                "grado": float(grado),
                "casa": int(casa)
            })
        # eclipse lunar (full moon near node)
        if abs(diff_sl - 180.0) < lunacion_tol and diff_node_sol < nodo_tol:
            signo, grado = obtener_signo_grado(luna_lon)
            casa = 12
            for i in range(12):
                a = cuspides_degs[i]
                b = cuspides_degs[(i+1)%12]
                long_n = luna_lon
                b_n = b
                if b < a:
                    if long_n < a:
                        long_n = long_n + 360
                    b_n = b + 360
                if a <= long_n < b_n:
                    casa = i+1
                    break
            eventos.append({
                "tipo": "eclipse",
                "subtipo": "lunar",
                "fecha": fecha.strftime("%Y-%m-%d"),
                "descripcion": f"Eclipse lunar (Luna llena cerca del nodo) - Cae en {signo} · Casa {casa}",
                "signo": signo,
                "grado": float(grado),
                "casa": int(casa)
            })

        fecha += timedelta(days=1)

    return eventos

# ---------- función central que ya tenías: calcular_transitos_planeta ----------
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
    sistema: Literal['P','W'] = 'P'

class RequestTransitosCielo(RequestTransitos):
    incluir_luna: bool = True

def calcular_transitos_planeta(
    planeta_num,
    nombre_planeta,
    fecha_inicio,
    fecha_final,
    año_natal, mes_natal, dia_natal, hora_natal, minuto_natal,
    latitud_natal, longitud_natal, zona_horaria_natal,
    sistema_casas='P',
    posiciones_natales: Dict[str, Any] = None,
):
    swe.set_ephe_path(EPHE_PATH)
    ASPECTOS_LABEL = {
        "conjuncion": "conjunción",
        "sextil": "sextil",
        "cuadratura": "cuadratura",
        "trigono": "trígono",
        "oposicion": "oposición",
    }

    # calculamos cúspides natales (necesarias para casa)
    hora_utc_natal = hora_natal - zona_horaria_natal
    dia_utc_natal = dia_natal
    if hora_utc_natal >= 24:
        hora_utc_natal -= 24; dia_utc_natal += 1
    elif hora_utc_natal < 0:
        hora_utc_natal += 24; dia_utc_natal -= 1

    jd_natal = swe.julday(año_natal, mes_natal, dia_utc_natal, hora_utc_natal + minuto_natal/60.0)
    casas_data = swe.houses(jd_natal, latitud_natal, longitud_natal, sistema_casas.encode())
    cuspides_placidus = list(casas_data[0][:12])
    ascendente = casas_data[1][0]
    signo_ascendente = int(ascendente // 30) % 12

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
                b = cuspides[(i+1)%12]
                long_n = long_ec
                b_n = b
                if b < a:
                    if long_ec < a:
                        long_n = long_ec + 360
                    b_n = b + 360
                if a <= long_n < b_n:
                    return i+1
            return 12

    eventos = []
    f_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    f_final = datetime.strptime(fecha_final, "%Y-%m-%d")

    if nombre_planeta == "LUNA":
        delta = timedelta(hours=1)
    elif nombre_planeta in ["SOL", "MERCURIO", "VENUS", "MARTE"]:
        delta = timedelta(hours=12)
    else:
        delta = timedelta(days=1)

    fecha_actual = f_inicio
    signo_anterior = None
    casa_anterior = None
    retrogrado_anterior = None

    estados_aspectos: Dict[str, Dict[str, Any]] = {}
    jd_prev = None
    fecha_prev = None

    while fecha_actual <= f_final:
        jd = swe.julday(fecha_actual.year, fecha_actual.month, fecha_actual.day, 12.0)
        try:
            res = swe.calc_ut(jd, planeta_num, swe.FLG_SWIEPH | swe.FLG_SPEED)
        except Exception as e:
            fecha_actual += delta
            continue
        longitud = float(res[0][0]) % 360.0
        velocidad = float(res[0][3])

        signo_actual_idx = int(longitud // 30) % 12
        signo_actual = SIGNOS[signo_actual_idx]
        grado_actual = float(longitud % 30.0)
        casa_actual = obtener_casa(longitud)
        retro_actual = velocidad < 0

        # cambio de signo
        if signo_anterior is not None and signo_actual_idx != signo_anterior:
            # aproximamos fecha exacta con búsqueda binaria simple entre fecha_prev y fecha_actual
            jd1 = swe.julday(fecha_prev.year, fecha_prev.month, fecha_prev.day, 12.0)
            jd2 = swe.julday(fecha_actual.year, fecha_actual.month, fecha_actual.day, 12.0)
            # no implementamos binary search full para no alargar; guardamos fecha_actual como momento
            eventos.append({
                "tipo": "cambio_signo",
                "planeta": nombre_planeta,
                "fecha": fecha_actual.strftime("%Y-%m-%d"),
                "descripcion": f"{nombre_planeta} ingresa a {signo_actual}",
                "signo": signo_actual,
                "grado": float(grado_actual),
                "casa": int(casa_actual)
            })

        # cambio de casa
        if casa_anterior is not None and casa_actual != casa_anterior:
            eventos.append({
                "tipo": "cambio_casa",
                "planeta": nombre_planeta,
                "fecha": fecha_actual.strftime("%Y-%m-%d"),
                "descripcion": f"{nombre_planeta} entra en casa {casa_actual}",
                "signo": signo_actual,
                "grado": float(grado_actual),
                "casa": int(casa_actual)
            })

        # retrogradación inicio / fin
        if retrogrado_anterior is not None and retro_actual != retrogrado_anterior:
            eventos.append({
                "tipo": "retrogrado_inicio" if retro_actual else "retrogrado_fin",
                "planeta": nombre_planeta,
                "fecha": fecha_actual.strftime("%Y-%m-%d"),
                "descripcion": f"{nombre_planeta} {'comienza' if retro_actual else 'termina'} movimiento retrógrado",
                "signo": signo_actual,
                "grado": float(grado_actual),
                "casa": int(casa_actual)
            })

        # aspectos contra posiciones natales (si posiciones_natales provistas)
        if posiciones_natales:
            for natal_name, natal_pos in posiciones_natales.items():
                if natal_name not in posiciones_natales: continue
                diff = (longitud - natal_pos["longitud"]) % 360.0
                for asp_name, asp_info in ASPECTOS.items():
                    ang = asp_info["angulo"]
                    orbe = asp_info["orbe"]
                    d = distancia_aspecto(diff, ang)
                    if d <= orbe:
                        # intento de momento exacto: simple búsqueda local entre jd-1 y jd+1
                        evento = {
                            "tipo": "aspecto",
                            "planeta": nombre_planeta,
                            "planeta_natal": natal_name,
                            "aspecto": asp_name,
                            "angulo": ang,
                            "orbe": d,
                            "fecha": fecha_actual.strftime("%Y-%m-%d"),
                            "descripcion": f"{nombre_planeta} {ASPECTOS_LABEL.get(asp_name,asp_name)} {natal_name}"
                        }
                        eventos.append(evento)

        # guardar estado prev
        signo_anterior = signo_actual_idx
        casa_anterior = casa_actual
        retrogrado_anterior = retro_actual
        fecha_prev = fecha_actual
        fecha_actual += delta

    # ordenar eventos por fecha
    def fecha_ev(e):
        f = e.get("fecha") or e.get("fecha_inicio") or e.get("fecha_exacto") or "1900-01-01"
        try:
            return datetime.strptime(f[:10], "%Y-%m-%d")
        except Exception:
            return datetime(1900,1,1)

    eventos = sorted(eventos, key=fecha_ev)

    # construir objeto planet_events (estructura esperada por frontend)
    planet_events = {
        "planeta": nombre_planeta,
        "posicion_inicial": None,
        "posicion_final": None,
        "eventos": eventos
    }
    return planet_events

def calcular_aspectos_transito_transito(posiciones_por_dia):
    """
    Calcula aspectos entre planetas en tránsito (transito vs transito)
    usando orbes cerrados para evitar duplicados y ruido.
    """
    ASPECTOS_T = {
        "conjuncion": {"angulo": 0, "orbe": 1},
        "sextil": {"angulo": 60, "orbe": 0.8},
        "cuadratura": {"angulo": 90, "orbe": 1},
        "trigono": {"angulo": 120, "orbe": 1},
        "oposicion": {"angulo": 180, "orbe": 1},
    }

    eventos = []
    vistos = set()

    # identificar planetas, excluyendo la fecha
    planetas = [p for p in posiciones_por_dia[0].keys() if p != "fecha"]

    for info in posiciones_por_dia:
        fecha = info["fecha"]

        for i in range(len(planetas)):
            for j in range(i + 1, len(planetas)):
                p1 = planetas[i]
                p2 = planetas[j]

                lon1 = info[p1]
                lon2 = info[p2]

                # diferencia angular 0–360
                diff = abs((lon1 - lon2) % 360)

                for asp, data in ASPECTOS_T.items():
                    angulo = data["angulo"]
                    orbe = data["orbe"]

                    # distancia angular mínima
                    distancia = min(
                        abs(diff - angulo),
                        abs(360 - abs(diff - angulo))
                    )

                    if distancia <= orbe:
                        clave = f"{fecha}_{p1}_{p2}_{asp}"
                        if clave in vistos:
                            continue
                        vistos.add(clave)

                        eventos.append({
                            "tipo": "aspecto_transito",
                            "planeta1": p1,
                            "planeta2": p2,
                            "aspecto": asp,
                            "fecha": fecha,
                            "descripcion": f"{p1} {asp} a {p2} (tránsito)"
                        })

    return eventos


@app.post("/calcular-transitos")
def api_calcular_transitos(req: RequestTransitos):
    try:
        # ---------------------------
        # 1) Construir posiciones natales (solo si modo = natal)
        # ---------------------------
        incluir_natal = getattr(req, "modo", "natal") == "natal"

        if incluir_natal:
            posiciones_natales = construir_posiciones_natales(
                req.año_natal, req.mes_natal, req.dia_natal,
                req.hora_natal, req.minuto_natal,
                req.latitud_natal, req.longitud_natal,
                req.zona_horaria_natal,
                sistema_casas=req.sistema
            )
        else:
            posiciones_natales = None

        # ---------------------------
        # 2) Lista de planetas
        # ---------------------------
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

        # ---------------------------
        # 3) Calcular eventos de cada planeta (signo, casa, retro, natal)
        # ---------------------------
        resultados = []
        for nombre, num in planetas.items():
            resultado = calcular_transitos_planeta(
                num, nombre,
                req.fecha_inicio, req.fecha_final,
                req.año_natal, req.mes_natal, req.dia_natal,
                req.hora_natal, req.minuto_natal,
                req.latitud_natal, req.longitud_natal,
                req.zona_horaria_natal,
                sistema_casas=req.sistema,
                posiciones_natales=posiciones_natales   # ← solo si modo natal
            )
            resultados.append(resultado)

        # ---------------------------
        # 4) Eclipses (siempre)
        # ---------------------------
        eclipses = detectar_eclipses(
            req.fecha_inicio, req.fecha_final,
            req.año_natal, req.mes_natal, req.dia_natal,
            req.hora_natal, req.minuto_natal,
            req.latitud_natal, req.longitud_natal,
            req.zona_horaria_natal, sistema=req.sistema
        )

        # ---------------------------
        # 5) Aspectos tránsito ↔ tránsito (solo si modo = cielo)
        # ---------------------------
        eventos_cielo = []

        if not incluir_natal:
            posiciones_por_dia = []
            fecha = datetime.strptime(req.fecha_inicio, "%Y-%m-%d")
            fin = datetime.strptime(req.fecha_final, "%Y-%m-%d")

            while fecha <= fin:
                jd = swe.julday(fecha.year, fecha.month, fecha.day, 12.0)
                pos_dia = {"fecha": fecha.strftime("%Y-%m-%d")}

                for nom, num in planetas.items():
                    pos_dia[nom] = swe.calc_ut(jd, num)[0][0] % 360

                posiciones_por_dia.append(pos_dia)
                fecha += timedelta(days=1)

            eventos_cielo = calcular_aspectos_transito_transito(posiciones_por_dia)

        # ---------------------------
        # 6) Respuesta final
        # ---------------------------
        return {
            "periodo": {
                "inicio": req.fecha_inicio,
                "fin": req.fecha_final
            },
            "modo": "natal" if incluir_natal else "cielo",
            "natal": {
                "fecha": f"{req.año_natal}-{req.mes_natal}-{req.dia_natal}",
                "hora": f"{req.hora_natal}:{req.minuto_natal}",
                "ubicacion": {
                    "lat": req.latitud_natal,
                    "lon": req.longitud_natal
                }
            } if incluir_natal else None,
            "transitos": resultados,
            "eclipses": eclipses,
            "aspectos_transito_transito": eventos_cielo
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/carta-natal-sola")
def api_carta_natal_sola(payload: dict):
    try:
        return calcular_carta_natal_sola(
            payload["año"],
            payload["mes"],
            payload["dia"],
            payload["hora"],
            payload.get("minuto", 0),
            float(payload["latitud"]),
            float(payload["longitud"]),
            int(payload["zona_horaria"]),
            sistema_casas=payload.get("sistema_casas", "P")
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))