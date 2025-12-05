# transitos.py
"""
Módulo profesional A1 (precisión por hora).
Exporta:
 - calcular_transitos_cielo(fecha_inicio, fecha_final, incluir_luna=True)
 - calcular_transitos_natal(fecha_inicio, fecha_final, posiciones_natales=None, cuspides=None, incluir_luna=True)
 - calcular_transitos_completo(...)  -> combina ambos
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
import swisseph as swe
import os


    
BASE_DIR = Path(__file__).resolve().parent
EPHE_PATH = str(BASE_DIR / "ephe")
os.makedirs(EPHE_PATH, exist_ok=True)
swe.set_ephe_path(EPHE_PATH)

PLANETAS = {
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

SIGNOS_NOMBRES = [
    "ARIES", "TAURO", "GÉMINIS", "CÁNCER", "LEO", "VIRGO",
    "LIBRA", "ESCORPIO", "SAGITARIO", "CAPRICORNIO", "ACUARIO", "PISCIS"
]

ASPECTOS = {
    "conjuncion": 0.0,
    "sextil": 60.0,
    "cuadratura": 90.0,
    "trigono": 120.0,
    "oposicion": 180.0
}

ASPECTOS_LABEL = {
    "conjuncion": "conjunción",
    "sextil": "sextil",
    "cuadratura": "cuadratura",
    "trigono": "trígono",
    "oposicion": "oposición"
}

ORBES_BASE = {
    "LUNA": 6.0,
    "SOL": 4.0,
    "MERCURIO": 3.0,
    "VENUS": 3.0,
    "MARTE": 2.5,
    "JUPITER": 2.0,
    "SATURNO": 2.0,
    "URANO": 1.5,
    "NEPTUNO": 1.5,
    "PLUTON": 1.5
}

DT_FMT = "%Y-%m-%d %H:%M"
DT_DAY_FMT = "%Y-%m-%d"

def _norm360(x: float) -> float:
    x = x % 360.0
    if x < 0:
        x += 360.0
    return x

def _ang_diff(a: float, b: float) -> float:
    diff = abs(_norm360(a) - _norm360(b))
    if diff > 180:
        diff = 360 - diff
    return diff

def distancia_aspecto(lon1: float, lon2: float, ang_obj: float) -> float:
    diff = _ang_diff(lon1, lon2)
    return abs(diff - ang_obj)

def _calc_long(jd: float, planeta_num: int) -> Optional[float]:
    try:
        return float(swe.calc_ut(jd, planeta_num)[0][0]) % 360.0
    except Exception:
        return None

def _fecha_str(dt: datetime) -> str:
    return dt.strftime(DT_FMT)

def _fecha_day_str(dt: datetime) -> str:
    return dt.strftime(DT_DAY_FMT)

def obtener_casa_desde_cuspides(long_ec: float, cuspides: List[float]) -> int:
    for i in range(12):
        a = cuspides[i]
        b = cuspides[(i + 1) % 12]
        long_n = long_ec
        b_n = b
        if b < a:
            if long_ec < a:
                long_n = long_ec + 360.0
            b_n = b + 360.0
        if a <= long_n < b_n:
            return i + 1
    return 12
def obtener_casa_desde_cuspides_o_wholesign(
    long_ec: float, 
    cuspides: List[float], 
    sistema: str = "P"
) -> int:
    """
    Calcula la casa según el sistema elegido.
    - P (Placidus): usa cúspides calculadas
    - W (Whole Sign): divide en 12 sectores desde el ASC
    """
    if sistema == "W":
        # Whole Sign: cada signo = 1 casa
        signo_punto = int(long_ec // 30) % 12
        signo_asc = int(cuspides[0] // 30) % 12  # cuspides[0] = ASC
        casa = ((signo_punto - signo_asc) % 12) + 1
        return casa
    else:
        # Placidus (original)
        return obtener_casa_desde_cuspides(long_ec, cuspides)
    
def calcular_transitos_cielo(fecha_inicio: str, fecha_final: str, incluir_luna: bool = True) -> List[Dict[str, Any]]:
    inicio_day = datetime.strptime(fecha_inicio, DT_DAY_FMT)
    final_day = datetime.strptime(fecha_final, DT_DAY_FMT)
    delta = timedelta(hours=1)

    planetas = list(PLANETAS.keys())
    if not incluir_luna and "LUNA" in planetas:
        planetas.remove("LUNA")

    out = {p: {"planeta": p, "posicion_inicial": None, "posicion_final": None, "eventos": []} for p in planetas}

    try:
        jd_ini = swe.julday(inicio_day.year, inicio_day.month, inicio_day.day, 12.0)
        jd_fin = swe.julday(final_day.year, final_day.month, final_day.day, 12.0)
        for p in planetas:
            n = PLANETAS[p]
            long_ini = _calc_long(jd_ini, n)
            long_fin = _calc_long(jd_fin, n)
            out[p]["posicion_inicial"] = {"longitud": float(long_ini), "grado": float(long_ini % 30)}
            out[p]["posicion_final"] = {"longitud": float(long_fin), "grado": float(long_fin % 30)}
    except Exception:
        pass

    ventanas = {}
    fecha = inicio_day
    last_end = final_day + timedelta(hours=23)

    while fecha <= last_end:
        jd = swe.julday(fecha.year, fecha.month, fecha.day, fecha.hour)

        longitudes = {}
        for p in planetas:
            longitudes[p] = _calc_long(jd, PLANETAS[p])

        for i in range(len(planetas)):
            for j in range(i + 1, len(planetas)):
                p1 = planetas[i]
                p2 = planetas[j]
                lon1 = longitudes.get(p1)
                lon2 = longitudes.get(p2)
                if lon1 is None or lon2 is None:
                    continue
                if p1 == p2:
                    continue

                for asp_name, ang in ASPECTOS.items():
                    orbe = min(ORBES_BASE.get(p1, 2.0), ORBES_BASE.get(p2, 2.0))
                    dist = distancia_aspecto(lon1, lon2, ang)
                    clave = f"{p1}__{p2}__{asp_name}"

                    estado = ventanas.get(clave)

                    if dist <= orbe and estado is None:
                        ventanas[clave] = {
                            "activo": True,
                            "fecha_inicio": _fecha_str(fecha),
                            "fecha_exacto": _fecha_str(fecha),
                            "dist_min": dist
                        }

                    elif estado is not None and estado.get("activo"):
                        if dist < estado.get("dist_min", 9999.0):
                            estado["dist_min"] = dist
                            estado["fecha_exacto"] = _fecha_str(fecha)

                        if dist > orbe:
                            estado["activo"] = False
                            evento = {
                                "tipo": "aspecto_transito",
                                "origen": "transito_transito",
                                "planeta1": p1,
                                "planeta2": p2,
                                "aspecto": asp_name,
                                "descripcion": f"{p1} {ASPECTOS_LABEL.get(asp_name, asp_name)} {p2}",
                                "fecha_inicio": estado["fecha_inicio"],
                                "fecha_exacto": estado["fecha_exacto"],
                                "fecha_fin": _fecha_str(fecha)
                            }
                            out[p1]["eventos"].append(evento)
                            out[p2]["eventos"].append(evento)

        fecha += delta
    # cerrar ventanas activas
    last_fin = (final_day + timedelta(hours=23)).strftime(DT_FMT)
    for clave, estado in list(ventanas.items()):
        if estado.get("activo"):
            partes = clave.split("__")
            if len(partes) >= 3:
                p1, p2, asp = partes[0], partes[1], partes[2]
                evento = {
                    "tipo": "aspecto_transito",
                    "origen": "transito_transito",
                    "planeta1": p1,
                    "planeta2": p2,
                    "aspecto": asp,
                    "descripcion": f"{p1} {ASPECTOS_LABEL.get(asp, asp)} {p2}",
                    "fecha_inicio": estado["fecha_inicio"],
                    "fecha_exacto": estado.get("fecha_exacto", estado["fecha_inicio"]),
                    "fecha_fin": last_fin
                }
                out[p1]["eventos"].append(evento)
                out[p2]["eventos"].append(evento)

    def _key(ev):
        for f in ("fecha_exacto", "fecha_inicio", "fecha_fin"):
            if f in ev and ev[f]:
                try:
                    return datetime.strptime(ev[f], DT_FMT)
                except Exception:
                    pass
        return datetime.min

    resultado = []
    for p in planetas:
        pe = out[p]
        pe["eventos"] = sorted(pe["eventos"], key=_key)
        resultado.append(pe)

    return resultado

# ============================================================
# TRANSITOS SOBRE CARTA NATAL
# ============================================================
def calcular_transitos_natal(
    fecha_inicio: str,
    fecha_final: str,
    posiciones_natales: Optional[Dict[str, float]] = None,
    cuspides: Optional[List[float]] = None,
    incluir_luna: bool = True,
    sistema: str = "P"  # ⬅️ NUEVO PARÁMETRO
) -> List[Dict[str, Any]]:

    inicio_day = datetime.strptime(fecha_inicio, DT_DAY_FMT)
    final_day = datetime.strptime(fecha_final, DT_DAY_FMT)
    delta = timedelta(hours=1)

    planetas = list(PLANETAS.keys())
    if not incluir_luna and "LUNA" in planetas:
        planetas.remove("LUNA")

    out = {
        p: {
            "planeta": p,
            "posicion_inicial": None,
            "posicion_final": None,
            "eventos": []
        }
        for p in planetas
    }

    try:
        jd_ini = swe.julday(inicio_day.year, inicio_day.month, inicio_day.day, 12.0)
        jd_fin = swe.julday(final_day.year, final_day.month, final_day.day, 12.0)
        for p in planetas:
            n = PLANETAS[p]
            long_ini = _calc_long(jd_ini, n)
            long_fin = _calc_long(jd_fin, n)
            out[p]["posicion_inicial"] = {"longitud": long_ini, "grado": long_ini % 30}
            out[p]["posicion_final"] = {"longitud": long_fin, "grado": long_fin % 30}
    except Exception:
        pass

    ventanas = {}
    estado_prev = {p: {"signo_idx": None, "casa": None, "retro": None} for p in planetas}

    fecha = inicio_day
    last_end = final_day + timedelta(hours=23)

    while fecha <= last_end:
        jd = swe.julday(fecha.year, fecha.month, fecha.day, fecha.hour)

        for p in planetas:
            n = PLANETAS[p]
            lon_now = _calc_long(jd, n)
            if lon_now is None:
                continue

            signo_idx = int(lon_now // 30) % 12
            prev_signo = estado_prev[p]["signo_idx"]

            if prev_signo is None:
                estado_prev[p]["signo_idx"] = signo_idx

            elif prev_signo != signo_idx:
                evento = {
                    "tipo": "cambio_signo",
                    "origen": "evento_transito",
                    "planeta": p,
                    "signo_anterior": prev_signo,
                    "signo_nuevo": signo_idx,
                    "descripcion": f"{p} ingresa a {SIGNOS_NOMBRES[signo_idx]}",
                    "fecha": _fecha_str(fecha)
                }
                out[p]["eventos"].append(evento)
                estado_prev[p]["signo_idx"] = signo_idx

            if cuspides and len(cuspides) == 12:
                # ⬇️ USAR LA NUEVA FUNCIÓN
                casa_now = obtener_casa_desde_cuspides_o_wholesign(lon_now, cuspides, sistema)
                prev_casa = estado_prev[p]["casa"]

                if prev_casa is None:
                    estado_prev[p]["casa"] = casa_now

                elif prev_casa != casa_now:
                    evento = {
                        "tipo": "cambio_casa",
                        "origen": "evento_transito",
                        "planeta": p,
                        "casa_anterior": prev_casa,
                        "casa_nueva": casa_now,
                        "casa": casa_now,
                        "descripcion": f"{p} ingresa a casa {casa_now}",
                        "fecha": _fecha_str(fecha)
                    }
                    out[p]["eventos"].append(evento)
                    estado_prev[p]["casa"] = casa_now

            try:
                vel = float(swe.calc_ut(jd, n, swe.FLG_SWIEPH | swe.FLG_SPEED)[0][3])
            except Exception:
                vel = None

            prev_retro = estado_prev[p]["retro"]

            if prev_retro is None and vel is not None:
                estado_prev[p]["retro"] = (vel < 0)

            elif vel is not None:
                is_retro = vel < 0
                if prev_retro != is_retro:
                    estado_prev[p]["retro"] = is_retro
                    evento = {
                        "tipo": "retro_inicio" if is_retro else "retro_fin",
                        "origen": "evento_transito",
                        "planeta": p,
                        "descripcion": f"{p} {'inicia' if is_retro else 'termina'} movimiento retrógrado",
                        "fecha": _fecha_str(fecha)
                    }
                    out[p]["eventos"].append(evento)

            if posiciones_natales:
                for natal_name, natal_long in posiciones_natales.items():
                    for asp_name, ang in ASPECTOS.items():
                        orbe = min(
                            ORBES_BASE.get(p, 2.0),
                            ORBES_BASE.get(natal_name, ORBES_BASE.get(p, 2.0))
                        )
                        dist = distancia_aspecto(lon_now, natal_long, ang)
                        clave = f"{p}__{natal_name}__{asp_name}"
                        estado = ventanas.get(clave)

                        if dist <= orbe and estado is None:
                            ventanas[clave] = {
                                "activo": True,
                                "fecha_inicio": _fecha_str(fecha),
                                "fecha_exacto": _fecha_str(fecha),
                                "dist_min": dist
                            }

                        elif estado is not None and estado.get("activo"):
                            if dist < estado.get("dist_min", 9999.0):
                                estado["dist_min"] = dist
                                estado["fecha_exacto"] = _fecha_str(fecha)

                            if dist > orbe:
                                estado["activo"] = False
                                evento = {
                                    "tipo": "aspecto",
                                    "origen": "transito_natal",
                                    "planeta_transito": p,
                                    "planeta_natal": natal_name,
                                    "aspecto": asp_name,
                                    "descripcion": f"{p} {ASPECTOS_LABEL.get(asp_name, asp_name)} {natal_name}",
                                    "fecha_inicio": estado["fecha_inicio"],
                                    "fecha_exacto": estado["fecha_exacto"],
                                    "fecha_fin": _fecha_str(fecha)
                                }
                                out[p]["eventos"].append(evento)

        fecha += delta

    last_fin = (final_day + timedelta(hours=23)).strftime(DT_FMT)

    for clave, estado in list(ventanas.items()):
        if estado.get("activo"):
            partes = clave.split("__")
            if len(partes) >= 3:
                p, natal, asp = partes
                evento = {
                    "tipo": "aspecto",
                    "origen": "transito_natal",
                    "planeta_transito": p,
                    "planeta_natal": natal,
                    "aspecto": asp,
                    "descripcion": f"{p} {ASPECTOS_LABEL.get(asp, asp)} {natal}",
                    "fecha_inicio": estado["fecha_inicio"],
                    "fecha_exacto": estado.get("fecha_exacto", estado["fecha_inicio"]),
                    "fecha_fin": last_fin
                }
                out[p]["eventos"].append(evento)

    def _key(ev):
        for f in ("fecha_exacto", "fecha_inicio", "fecha"):
            if f in ev and ev[f]:
                try:
                    return datetime.strptime(ev[f], DT_FMT)
                except:
                    try:
                        return datetime.strptime(ev[f], DT_DAY_FMT)
                    except:
                        pass
        return datetime.min

    resultado = []
    for p in planetas:
        pe = out[p]
        pe["eventos"] = sorted(pe["eventos"], key=_key)
        resultado.append(pe)

    return resultado
# ============================================================
# COMBINADOR
# ============================================================
def calcular_transitos_completo(
    fecha_inicio: str,
    fecha_final: str,
    posiciones_natales: Optional[Dict[str, float]] = None,
    cuspides: Optional[List[float]] = None,
    incluir_luna: bool = True,
    incluir_cielo: bool = True,
    sistema: str = "P"
) -> Dict[str, Any]:
    salida = {
        "periodo": {"inicio": fecha_inicio, "fin": fecha_final},
        "transitos_natal": [],
        "transitos_cielo": [],
        "eclipses": [] ,
        "fases_lunares": []
    }
    
    if posiciones_natales:
        salida["transitos_natal"] = calcular_transitos_natal(
            fecha_inicio, fecha_final, posiciones_natales, cuspides, incluir_luna,
            sistema=sistema
        )
    
    if incluir_cielo:
        salida["transitos_cielo"] = calcular_transitos_cielo(
            fecha_inicio, fecha_final, incluir_luna
        )
    
    # CALCULAR ECLIPSES
    salida["eclipses"] = calcular_eclipses(fecha_inicio, fecha_final)
    salida["fases_lunares"] = calcular_fases_lunares(fecha_inicio, fecha_final)

    
    return salida
# Agregar esta función a transitos.py

def calcular_eclipses(fecha_inicio: str, fecha_final: str) -> List[Dict[str, Any]]:
    inicio_day = datetime.strptime(fecha_inicio, DT_DAY_FMT)
    final_day = datetime.strptime(fecha_final, DT_DAY_FMT)

    jd_inicio = swe.julday(inicio_day.year, inicio_day.month, inicio_day.day, 0)
    jd_final  = swe.julday(final_day.year, final_day.month, final_day.day, 23.99)

    eclipses = []

    # -----------------------------
    # 🌞 ECLIPSES SOLARES
    # -----------------------------
    jd = jd_inicio - 40
    while True:
        res = swe.sol_eclipse_when_glob(jd, swe.FLG_SWIEPH)
        jd_eclipse = res[1][0]

        if jd_eclipse > jd_final:
            break

        if jd_eclipse >= jd_inicio:
            y, m, d = swe.revjul(jd_eclipse)[:3]
            long_sol = _calc_long(jd_eclipse, swe.SUN)
            signo = SIGNOS_NOMBRES[int(long_sol // 30)]

            # Tipo correcto
            flags = res[0]
            if flags & swe.ECL_TOTAL:
                tipo = "Eclipse Solar Total"
            elif flags & swe.ECL_ANNULAR:
                tipo = "Eclipse Solar Anular"
            elif flags & swe.ECL_PARTIAL:
                tipo = "Eclipse Solar Parcial"
            else:
                tipo = "Eclipse Solar"

            eclipses.append({
                "tipo": "eclipse",
                "subtipo": "solar",
                "descripcion": f"{tipo} en {signo}",
                "fecha": f"{y}-{m:02d}-{d:02d}",
                "signo": signo,
                "grado": long_sol % 30,
                "planeta": "SOL"
            })

        jd = jd_eclipse + 170  # Saltar al siguiente posible eclipse


    # -----------------------------
    # 🌕 ECLIPSES LUNARES
    # -----------------------------
    jd = jd_inicio - 40
    while True:
        res = swe.lun_eclipse_when(jd, swe.FLG_SWIEPH)
        jd_eclipse = res[1][0]

        if jd_eclipse > jd_final:
            break

        if jd_eclipse >= jd_inicio:
            y, m, d = swe.revjul(jd_eclipse)[:3]
            long_luna = _calc_long(jd_eclipse, swe.MOON)
            signo = SIGNOS_NOMBRES[int(long_luna // 30)]

            flags = res[0]
            if flags & swe.ECL_TOTAL:
                tipo = "Eclipse Lunar Total"
            elif flags & swe.ECL_PARTIAL:
                tipo = "Eclipse Lunar Parcial"
            elif flags & swe.ECL_PENUMBRAL:
                tipo = "Eclipse Lunar Penumbral"
            else:
                tipo = "Eclipse Lunar"

            eclipses.append({
                "tipo": "eclipse",
                "subtipo": "lunar",
                "descripcion": f"{tipo} en {signo}",
                "fecha": f"{y}-{m:02d}-{d:02d}",
                "signo": signo,
                "grado": long_luna % 30,
                "planeta": "LUNA"
            })

        jd = jd_eclipse + 170

    return eclipses

def calcular_fases_lunares(fecha_inicio: str, fecha_final: str) -> List[Dict[str, Any]]:
    """
    Calcula Luna Nueva, Cuarto Creciente, Luna Llena y Cuarto Menguante
    encontrando el momento EXACTO en que la elongación Sol–Luna = 0°, 90°, 180°, 270°.
    Usa interpolación lineal con paso de 30 minutos para alta precisión.
    """

    inicio = datetime.strptime(fecha_inicio, DT_DAY_FMT)
    fin = datetime.strptime(fecha_final, DT_DAY_FMT)
    delta = timedelta(minutes=30)

    fases = []
    objetivos = {
        "Luna Nueva": 0,
        "Cuarto Creciente": 90,
        "Luna Llena": 180,
        "Cuarto Menguante": 270
    }

    fecha = inicio

    while fecha <= fin + timedelta(days=1):  # Asegura cubrir el último día completo
        jd = swe.julday(
            fecha.year, fecha.month, fecha.day,
            fecha.hour + fecha.minute / 60.0
        )

        lon_sol = _calc_long(jd, swe.SUN)
        lon_luna = _calc_long(jd, swe.MOON)

        if lon_sol is None or lon_luna is None:
            fecha += delta
            continue

        elong = (lon_luna - lon_sol) % 360

        # Siguiente punto temporal para interpolación
        fecha_next = fecha + delta
        jd_next = swe.julday(
            fecha_next.year, fecha_next.month, fecha_next.day,
            fecha_next.hour + fecha_next.minute / 60.0
        )

        lon_sol_next = _calc_long(jd_next, swe.SUN)
        lon_luna_next = _calc_long(jd_next, swe.MOON)

        if lon_sol_next is None or lon_luna_next is None:
            fecha += delta
            continue

        elong_next = (lon_luna_next - lon_sol_next) % 360

        # Buscar cruces con las elongaciones objetivo
        for nombre, ang_obj in objetivos.items():

            diff = abs(elong - ang_obj)
            diff_next = abs(elong_next - ang_obj)

            # Condiciones de cruce o cercanía
            cruza = (
                diff <= 1 or diff_next <= 1 or
                (elong <= ang_obj <= elong_next) or
                (elong_next <= ang_obj <= elong) or
                (elong > elong_next and (elong <= ang_obj or ang_obj <= elong_next))
            )

            if cruza:
                # Interpolación lineal
                if elong_next != elong:
                    frac = (ang_obj - elong) / (elong_next - elong)
                    if frac < 0:  # Ajustar wrap-around
                        frac += 1
                    fecha_exacta = fecha + frac * delta
                else:
                    fecha_exacta = fecha

                jd_exacta = swe.julday(
                    fecha_exacta.year, fecha_exacta.month, fecha_exacta.day,
                    fecha_exacta.hour + fecha_exacta.minute / 60.0
                )

                lon_luna_exacta = _calc_long(jd_exacta, swe.MOON)
                if lon_luna_exacta is not None:
                    signo = SIGNOS_NOMBRES[int(lon_luna_exacta // 30)]
                    fases.append({
                        "tipo": "fase_lunar",
                        "subtipo": nombre,
                        "descripcion": f"{nombre} en {signo}",
                        "fecha": fecha_exacta.strftime("%Y-%m-%d %H:%M:%S"),
                        "signo": signo,
                        "grado": lon_luna_exacta % 30,
                        "planeta": "LUNA"
                    })

        fecha += delta

    # ---- FILTRO: una fase por tipo por mes ----
    fases_filtradas = {}
    for f in fases:
        mes = f["fecha"][:7]  # YYYY-MM
        clave = f"{f['subtipo']}_{mes}"
        if clave not in fases_filtradas:
            fases_filtradas[clave] = f

    fases_unicas = list(fases_filtradas.values())
    fases_unicas.sort(key=lambda x: x["fecha"])

    print(
        f"DEBUG: Encontradas {len(fases)} fases lunares crudas, "
        f"filtradas a {len(fases_unicas)} importantes entre {fecha_inicio} y {fecha_final}"
    )

    return fases_unicas

# --- NUEVO: Calcular cúspides (casa) desde fecha/hora natal y coordenadas ---
def calcular_cuspides_desde_natal(year: int, month: int, day: int, hour: int, minute: int,
                                  lat: float, lon: float, sistema: str = "P") -> List[float]:
    """
    Devuelve lista de 12 cúspides (grados eclípticos) usando swe.houses.
    'sistema' acepta letras de SWisseph (e.g., 'P' Placidus, 'W' Whole sign? revisar).
    Retorna lista de 12 floats (cada cúspide en grados 0-360).
    """
    jd = swe.julday(year, month, day, hour + (minute or 0) / 60.0)
    try:
        # swe.houses devuelve (cusps, ascmc)
        cusps, ascmc = swe.houses(jd, lat, lon, sistema)
        # cusps es iterable; devolvemos los primeros 12 (convertir a float)
        return [float(c) for c in cusps[:12]]
    except Exception as e:
        # si falla, retornamos None o lista vacía para que el caller pueda ignorarlo
        return None
