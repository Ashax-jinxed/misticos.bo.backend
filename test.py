import swisseph as swe
from datetime import date

EPHE_PATH = "./ephe"  # Ajusta si tu carpeta se llama distinto
swe.set_ephe_path(EPHE_PATH)

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
    "NODO_NORTE": swe.MEAN_NODE,   # ESTE SÍ EXISTE EN TODAS LAS VERSIONES
    "QUIRON": swe.CHIRON           # QUIRÓN TAMBIÉN EXISTE
}

FECHAS = [
    date(2023, 1, 1),
    date(2023, 2, 15),
    date(2023, 3, 7),   # Saturno debería entrar a Piscis
    date(2023, 4, 1),
    date(2024, 1, 1),
    date(2025, 1, 1)
]

def signo(lon):
    signos = ["Aries","Tauro","Geminis","Cancer","Leo","Virgo",
              "Libra","Escorpio","Sagitario","Capricornio","Acuario","Piscis"]
    return signos[int(lon//30)%12]

print("\n========= TEST REAL =========\n")

for f in FECHAS:
    jd = swe.julday(f.year,f.month,f.day,12.0)
    print(f"📅 {f}")
    print("------------------------")
    for nombre,cod in PLANETAS.items():
        lon = swe.calc_ut(jd,cod)[0][0]
        print(f"{nombre:<10} → {signo(lon):9}  {lon%30:05.2f}°")
    print()
