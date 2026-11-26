import os
import swisseph as swe

RUTA_EPHE = os.path.abspath("ephe")
swe.set_ephe_path(RUTA_EPHE)

print("ruta ephe:", RUTA_EPHE)
print("archivos:", sorted(os.listdir(RUTA_EPHE)) if os.path.exists(RUTA_EPHE) else "NO EXISTE")

jd = swe.julday(1990, 1, 1, 12.0)

try:
    xx, ret = swe.calc_ut(jd, swe.CHIRON, swe.FLG_SWIEPH)
    print("longitud:", xx[0], "retflag:", ret)

    if ret == swe.FLG_SWIEPH:
        print("OK: usando seas_18.se1")
    elif ret == swe.FLG_MOSEPH:
        print("ATENCION: cayó a Moshier, no está leyendo seas_18.se1")
    elif ret < 0:
        print("ERROR de Swiss Ephemeris, retflag negativo")
except Exception as e:
    print("EXCEPCIÓN:", e)