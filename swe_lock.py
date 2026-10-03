"""Candado global para serializar el acceso a pyswisseph (que mantiene estado global en C)."""
import functools
import threading

SWE_LOCK = threading.RLock()  # reentrante: las funciones protegidas pueden llamarse entre sí


def con_lock_swe(fn):
    @functools.wraps(fn)
    def envoltorio(*args, **kwargs):
        with SWE_LOCK:
            return fn(*args, **kwargs)
    return envoltorio
