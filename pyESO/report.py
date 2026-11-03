"""Affichage et controles : logs horodates, empreintes, verifications."""
import hashlib
import random
import time
from datetime import datetime


class PyESOError(Exception):
    """Erreur qui doit arreter le traitement en cours (equivalent de fail() + set -e en bash)."""


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def fail(msg: str):
    raise PyESOError(msg)


def fp(value: str | bytes) -> str:
    """Empreinte courte (sha256, 12 caracteres) : identifie une cle sans l'afficher."""
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()[:12]


def stamp() -> str:
    """Valeur unique pour une annotation de declenchement."""
    return f"{int(time.time())}-{random.randint(0, 32767)}"


def expect(label: str, want, got) -> None:
    if want != got:
        fail(f"{label} : attendu {want}, obtenu {got}")
    log(f"  OK   {label} : {got}")
