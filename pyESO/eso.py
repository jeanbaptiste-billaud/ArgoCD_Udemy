"""External Secrets Operator : declencher une synchro et attendre qu'elle soit faite.

Avec refreshInterval: 0s (PushSecret) ou refreshPolicy: OnChange (ExternalSecret),
ESO ne synchronise que quand l'objet change : une annotation suffit a le declencher.
"""
import time

from pyESO import kube
from pyESO.report import fail, log, stamp

# Groupe, version et pluriel des CRD ESO (kubectl api-resources | grep external-secrets)
KINDS = {
    "externalsecret": ("external-secrets.io", "v1", "externalsecrets"),
    "pushsecret": ("external-secrets.io", "v1alpha1", "pushsecrets"),
}


def get(ns: str, kind: str, name: str) -> dict:
    group, version, plural = KINDS[kind]
    return kube.custom().get_namespaced_custom_object(group, version, ns, plural, name)


def _state(obj: dict) -> tuple[str | None, str | None]:
    status = obj.get("status", {})
    ready = next((c["status"] for c in status.get("conditions", []) if c["type"] == "Ready"), None)
    return status.get("refreshTime"), ready


def trigger(ns: str, kind: str, name: str, timeout: float = 60) -> None:
    """Annote l'objet puis attend un nouveau refreshTime avec Ready=True."""
    group, version, plural = KINDS[kind]
    before, _ = _state(get(ns, kind, name))
    kube.custom().patch_namespaced_custom_object(
        group, version, ns, plural, name,
        {"metadata": {"annotations": {"force-sync": stamp()}}},
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        now, ready = _state(get(ns, kind, name))
        if now != before and ready == "True":
            log(f"  {kind}/{name} synchronise")
            return
    fail(f"{kind}/{name} non synchronise en {timeout} s")
