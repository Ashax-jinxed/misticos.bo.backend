from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal, Dict, Any
import swisseph as swe
import os
from pathlib import Path
from datetime import datetime, timedelta

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


# Lista de signos global para reutilizar
SIGNOS = [
    "ARIES","TAURO","GEMINIS","CANCER","LEO","VIRGO",
    "LIBRA","ESCORPIO","SAGITARIO","CAPRICORNIO","ACUARIO","PISCIS"
]

# Aspectos a considerar y orbes en grados
ASPECTOS = {
    "conjuncion": {"angulo": 0, "orbe": 6},
    "sextil": {"angulo": 60, "orbe": 4},
    "cuadratura": {"angulo": 90, "orbe": 5},
    "trigono": {"angulo": 120, "orbe": 5},
    "oposicion": {"angulo": 180, "orbe": 6},
}

# Cuerpos natales relevantes para aspectos
CUERPOS_NATALES_RELEVANTES = {
    "SOL", "LUNA", "MERCURIO", "VENUS", "MARTE",
    "JUPITER", "SATURNO", "URANO", "NEPTUNO", "PLUTON",
    "ASCENDENTE", "MEDIO_CIELO",
    "NODO_NORTE", "NODO_SUR",
    "LILITH", "QUIRON",
}

# Planetas con "retorno" relevante
PLANETAS_RETORNO = {"JUPITER", "SATURNO", "QUIRON", "NODO_NORTE"}


def obtener_signo_grado(longitud_ec: float):
    signo_index = int(longitud_ec // 30) % 12
    grado = (longitud_ec % 30)
    return SIGNOS[signo_index], grado


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
        'casa': 1,
        'retrogrado': False,
        'longitud': float(ascendente)
    }
    signo_mc, grado_mc = obtener_signo_grado(mc)
    carta['MEDIO_CIELO'] = {
        'signo': signo_mc,
        'grado': float(grado_mc),
        'casa': 10,
        'retrogrado': False,
        'longitud': float(mc)
    }

    # devolver cúspides como signos
    cuspides_signos = {}
    for idx, cdeg in enumerate(cuspides, start=1):
        signo_idx = int(cdeg // 30) % 12
        cuspides_signos[str(idx)] = SIGNOS[signo_idx]

    return {
        "carta": carta,
        "cuspides": cuspides_signos
    }


def construir_posiciones_natales(año, mes, dia, hora, minuto, latitud, longitud, zona_horaria, sistema_casas='P') -> Dict[str, Any]:
    """
    Utilidad: obtiene carta natal y devuelve solo las posiciones natales relevantes
    (incluyendo longitudes) para cálculo de aspectos de tránsitos.
    """
    datos = calcular_carta_natal(
        año, mes, dia, hora, minuto,
        latitud, longitud, zona_horaria,
        sistema_casas=sistema_casas
    )
    carta = datos.get("carta", {})
    posiciones = {}
    for nombre, info in carta.items():
        if nombre in CUERPOS_NATALES_RELEVANTES and "longitud" in info:
            posiciones[nombre] = {
                "longitud": float(info["longitud"]),
                "casa": int(info.get("casa", 0)),
                "signo": info.get("signo")
            }
    return posiciones


def distancia_aspecto(diff_raw: float, angulo_objetivo: float) -> float:
    """
    diff_raw: diferencia en grados (0..360) entre tránsito y natal (long_transito - long_natal)
    angulo_objetivo: 0, 60, 90, 120, 180
    """
    diff_raw = diff_raw % 360.0
    if angulo_objetivo == 0:
        # conjunción
        return min(diff_raw, 360.0 - diff_raw)
    if angulo_objetivo == 180:
        # oposición
        return abs(diff_raw - 180.0)
    # otros aspectos: considerar ángulo y su complemento 360-ángulo
    return min(abs(diff_raw - angulo_objetivo), abs(diff_raw - (360.0 - angulo_objetivo)))


def encontrar_momento_aspecto(jd1: float, jd2: float, planeta_num: int, natal_long: float, angulo_objetivo: float):
    """
    Búsqueda binaria para encontrar el momento donde el aspecto es más exacto
    dentro del intervalo [jd1, jd2].
    Devuelve (jd_exacto, longitud_transito_exacto).
    """
    for _ in range(22):
        mid = (jd1 + jd2) / 2.0
        lon1 = swe.calc_ut(jd1, planeta_num, swe.FLG_SWIEPH)[0][0] % 360.0
        lonm = swe.calc_ut(mid, planeta_num, swe.FLG_SWIEPH)[0][0] % 360.0

        diff1 = (lon1 - natal_long) % 360.0
        diffm = (lonm - natal_long) % 360.0

        d1 = distancia_aspecto(diff1, angulo_objetivo)
        dm = distancia_aspecto(diffm, angulo_objetivo)

        if d1 < dm:
            jd2 = mid
        else:
            jd1 = mid

    jd_exacto = (jd1 + jd2) / 2.0
    lon_exacta = swe.calc_ut(jd_exacto, planeta_num, swe.FLG_SWIEPH)[0][0] % 360.0
    return jd_exacto, lon_exacta


def encontrar_ingreso_signo(jd1, jd2, planeta_num):
    """
    Dado un intervalo [jd1, jd2] donde sabemos que hubo cambio de signo,
    usamos búsqueda binaria para encontrar la fecha exacta del ingreso.
    """
    for _ in range(22):  # suficiente para precisión muy alta
        mid = (jd1 + jd2) / 2
        lon1 = swe.calc_ut(jd1, planeta_num, swe.FLG_SWIEPH)[0][0] % 360
        lonm = swe.calc_ut(mid, planeta_num, swe.FLG_SWIEPH)[0][0] % 360

        if int(lon1 // 30) == int(lonm // 30):
            jd1 = mid
        else:
            jd2 = mid
    return jd2


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


def calcular_transitos_planeta(
    planeta_num,
    nombre_planeta,
    fecha_inicio,
    fecha_final, 
    año_natal,
    mes_natal,
    dia_natal,
    hora_natal,
    minuto_natal,
    latitud_natal,
    longitud_natal,
    zona_horaria_natal,
    sistema_casas='P',
    posiciones_natales: Dict[str, Any] = None,
):
    """
    Calcula todos los tránsitos de un planeta entre dos fechas.
    Retorna lista de eventos: cambios de signo, casa, retrogradaciones y aspectos.
    TODOS los eventos incluyen un campo 'descripcion'.
    """
    swe.set_ephe_path(EPHE_PATH)

    # etiquetas bonitas para aspectos
    ASPECTOS_LABEL = {
        "conjuncion": "conjunción",
        "sextil": "sextil",
        "cuadratura": "cuadratura",
        "trigono": "trígono",
        "oposicion": "oposición",
    }
    
    # Calcular casas natales para obtener cúspides
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
    
    # Función para calcular casa en tránsitos (sobre carta natal)
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
    
    # Incremento según planeta
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

    # Estados para ventanas de aspecto
    estados_aspectos: Dict[str, Dict[str, Any]] = {}

    def key_aspecto(nombre_natal: str, aspecto: str) -> str:
        return f"{nombre_planeta}__{nombre_natal}__{aspecto}"

    jd_prev = None
    fecha_prev = None
    
    while fecha_actual <= f_final:
        jd = swe.julday(fecha_actual.year, fecha_actual.month, fecha_actual.day, 12.0)
        
        try:
            res = swe.calc_ut(jd, planeta_num, swe.FLG_SWIEPH | swe.FLG_SPEED)
            longitud = float(res[0][0]) % 360.0
            velocidad = float(res[0][3])
            
            signo_actual_idx = int(longitud // 30) % 12
            signo_actual = SIGNOS[signo_actual_idx]
            grado_actual = float(longitud % 30.0)
            casa_actual = obtener_casa(longitud)
            retrogrado_actual = velocidad < 0
            
            # CAMBIO DE SIGNO
            if signo_anterior is not None and signo_actual_idx != signo_anterior:
                jd_prev_signo = swe.julday(
                    fecha_prev.year,
                    fecha_prev.month,
                    fecha_prev.day,
                    12.0
                ) if fecha_prev is not None else jd - 1.0
                jd_ingreso = encontrar_ingreso_signo(jd_prev_signo, jd, planeta_num)
                y, m, d, _ = swe.revjul(jd_ingreso)
                eventos.append({
                    "tipo": "cambio_signo",
                    "planeta": nombre_planeta,
                    "fecha": f"{y}-{m:02d}-{d:02d}",
                    "signo_anterior": SIGNOS[signo_anterior],
                    "signo_nuevo": signo_actual,
                    "descripcion": f"{nombre_planeta} ingresa a {signo_actual}",
                    "longitud": longitud,
                    "grado": grado_actual
                })
            
            # CAMBIO DE CASA
            if casa_anterior is not None and casa_actual != casa_anterior:
                eventos.append({
                    "tipo": "cambio_casa",
                    "planeta": nombre_planeta,
                    "fecha": fecha_actual.strftime("%Y-%m-%d"),
                    "casa_anterior": casa_anterior,
                    "casa_nueva": casa_actual,
                    "descripcion": f"{nombre_planeta} ingresa a casa {casa_actual}",
                    "longitud": longitud,
                    "signo": signo_actual,
                    "grado": grado_actual
                })
            
            # RETROGRADO / DIRECTO
            if retrogrado_anterior is not None and retrogrado_actual != retrogrado_anterior:
                eventos.append({
                    "tipo": "retrogrado_inicio" if retrogrado_actual else "retrogrado_fin",
                    "planeta": nombre_planeta,
                    "fecha": fecha_actual.strftime("%Y-%m-%d"),
                    "descripcion": f"{nombre_planeta} inicia retrogradación" if retrogrado_actual else f"{nombre_planeta} termina retrogradación",
                    "longitud": longitud,
                    "signo": signo_actual,
                    "grado": grado_actual
                })

            # ASPECTOS A LA CARTA NATAL
            if posiciones_natales:
                for nombre_natal, info_natal in posiciones_natales.items():
                    natal_long = float(info_natal["longitud"])
                    diff_raw = (longitud - natal_long) % 360.0

                    for nombre_aspecto, cfg in ASPECTOS.items():
                        angulo = cfg["angulo"]
                        orbe = cfg["orbe"]
                        dist = distancia_aspecto(diff_raw, angulo)

                        clave = key_aspecto(nombre_natal, nombre_aspecto)
                        estado = estados_aspectos.get(clave)

                        dentro_orbe = dist <= orbe

                        # Entrando en orbe
                        if (estado is None or not estado.get("activo")) and dentro_orbe:
                            estado = {
                                "activo": True,
                                "fecha_inicio": fecha_actual.strftime("%Y-%m-%d"),
                                "jd_inicio": jd,
                                "orbe_max": orbe,
                                "angulo": angulo,
                                "natal_long": natal_long,
                                "nombre_natal": nombre_natal,
                                "nombre_aspecto": nombre_aspecto,
                            }

                            # Momento exacto del aspecto
                            if jd_prev is not None:
                                jd_exacto, lon_exacto = encontrar_momento_aspecto(
                                    jd_prev, jd, planeta_num, natal_long, angulo
                                )
                                y_e, m_e, d_e, _ = swe.revjul(jd_exacto)
                                fecha_exacto = f"{y_e}-{m_e:02d}-{d_e:02d}"
                                estado["fecha_exacto"] = fecha_exacto
                                estado["jd_exacto"] = jd_exacto
                                estado["longitud_transito_exacto"] = lon_exacto % 360.0
                            else:
                                estado["fecha_exacto"] = fecha_actual.strftime("%Y-%m-%d")
                                estado["jd_exacto"] = jd
                                estado["longitud_transito_exacto"] = longitud

                            estados_aspectos[clave] = estado

                        # Saliendo del orbe
                        elif estado is not None and estado.get("activo") and not dentro_orbe:
                            fecha_fin = fecha_actual.strftime("%Y-%m-%d")

                            nombre_natal = estado["nombre_natal"]
                            nombre_aspecto = estado["nombre_aspecto"]
                            etiqueta = ASPECTOS_LABEL.get(nombre_aspecto, nombre_aspecto)
                            es_retorno = (
                                nombre_aspecto == "conjuncion"
                                and nombre_planeta == nombre_natal
                                and nombre_planeta in PLANETAS_RETORNO
                            )

                            if es_retorno:
                                descripcion = f"Retorno de {nombre_planeta}"
                            else:
                                descripcion = f"{nombre_planeta} {etiqueta} a {nombre_natal} natal"

                            eventos.append({
                                "tipo": "retorno_planeta" if es_retorno else "aspecto",
                                "planeta_transito": nombre_planeta,
                                "planeta_natal": nombre_natal,
                                "aspecto": nombre_aspecto,
                                "angulo": estado["angulo"],
                                "orbe_max": estado["orbe_max"],
                                "fecha_inicio": estado["fecha_inicio"],
                                "fecha_exacto": estado.get("fecha_exacto", estado["fecha_inicio"]),
                                "fecha_fin": fecha_fin,
                                "longitud_transito_exacto": estado.get("longitud_transito_exacto", longitud),
                                "longitud_natal": natal_long,
                                "casa_transito_aprox": casa_actual,
                                "es_retorno": es_retorno,
                                "descripcion": descripcion
                            })

                            estado["activo"] = False
                            estados_aspectos[clave] = estado

            signo_anterior = signo_actual_idx
            casa_anterior = casa_actual
            retrogrado_anterior = retrogrado_actual
            jd_prev = jd
            fecha_prev = fecha_actual
            
        except Exception as e:
            print(f"Error calculando {nombre_planeta} en {fecha_actual}: {e}")
        
        fecha_actual += delta
    
    # Cerrar aspectos aún activos al final del período
    if posiciones_natales:
        for clave, estado in estados_aspectos.items():
            if estado.get("activo"):
                partes = clave.split("__")
                if len(partes) == 3:
                    _, nombre_natal, nombre_aspecto = partes
                else:
                    nombre_natal = "DESCONOCIDO"
                    nombre_aspecto = "desconocido"

                etiqueta = ASPECTOS_LABEL.get(nombre_aspecto, nombre_aspecto)
                es_retorno = (
                    nombre_aspecto == "conjuncion"
                    and nombre_planeta == nombre_natal
                    and nombre_planeta in PLANETAS_RETORNO
                )

                if es_retorno:
                    descripcion = f"Retorno de {nombre_planeta}"
                else:
                    descripcion = f"{nombre_planeta} {etiqueta} a {nombre_natal} natal"

                eventos.append({
                    "tipo": "retorno_planeta" if es_retorno else "aspecto",
                    "planeta_transito": nombre_planeta,
                    "planeta_natal": nombre_natal,
                    "aspecto": nombre_aspecto,
                    "angulo": estado["angulo"],
                    "orbe_max": estado["orbe_max"],
                    "fecha_inicio": estado["fecha_inicio"],
                    "fecha_exacto": estado.get("fecha_exacto", estado["fecha_inicio"]),
                    "fecha_fin": fecha_final,
                    "longitud_transito_exacto": estado.get("longitud_transito_exacto"),
                    "longitud_natal": estado.get("natal_long"),
                    "casa_transito_aprox": None,
                    "es_retorno": es_retorno,
                    "descripcion": descripcion
                })
    
    # Información inicial y final
    jd_inicio = swe.julday(f_inicio.year, f_inicio.month, f_inicio.day, 12.0)
    jd_final = swe.julday(f_final.year, f_final.month, f_final.day, 12.0)
    
    try:
        res_inicio = swe.calc_ut(jd_inicio, planeta_num, swe.FLG_SWIEPH | swe.FLG_SPEED)
        long_inicio = float(res_inicio[0][0]) % 360.0
        vel_inicio = float(res_inicio[0][3])
        signo_inicio = int(long_inicio // 30) % 12
        casa_inicio = obtener_casa(long_inicio)
        
        res_final = swe.calc_ut(jd_final, planeta_num, swe.FLG_SWIEPH | swe.FLG_SPEED)
        long_final = float(res_final[0][0]) % 360.0
        vel_final = float(res_final[0][3])
        signo_final = int(long_final // 30) % 12
        casa_final = obtener_casa(long_final)
        
        posicion_inicial = {
            "signo": SIGNOS[signo_inicio],
            "casa": casa_inicio,
            "grado": float(long_inicio % 30),
            "retrogrado": vel_inicio < 0,
            "longitud": long_inicio,
        }
        
        posicion_final = {
            "signo": SIGNOS[signo_final],
            "casa": casa_final,
            "grado": float(long_final % 30),
            "retrogrado": vel_final < 0,
            "longitud": long_final,
        }
        
    except Exception as e:
        print(f"Error calculando posiciones inicial/final de {nombre_planeta}: {e}")
        posicion_inicial = None
        posicion_final = None
    
    # Orden por fecha
    def fecha_evento(ev):
        for campo in ["fecha", "fecha_inicio", "fecha_exacto"]:
            if campo in ev and ev[campo]:
                try:
                    return datetime.strptime(ev[campo], "%Y-%m-%d")
                except Exception:
                    continue
        return f_inicio

    eventos_ordenados = sorted(eventos, key=fecha_evento)

    return {
        "planeta": nombre_planeta,
        "posicion_inicial": posicion_inicial,
        "posicion_final": posicion_final,
        "eventos": eventos_ordenados
    }
