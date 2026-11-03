"""Acces a l'API Kubernetes : Secrets, Pods, Deployments.

kubectl n'a rien de magique : chaque commande est une requete HTTP vers l'API server
(GET, PATCH, ou un websocket pour exec). Le client Python appelle les memes endpoints
avec le meme token, donc le meme RBAC suffit.
"""
import base64
import time
from datetime import datetime, timezone
from functools import cache

from kubernetes import client, config
from kubernetes.stream import stream

from pyESO.report import fail, stamp


@cache
def _load_config() -> None:
    # Dans un pod : token du ServiceAccount monte. Sinon : ~/.kube/config (ou $KUBECONFIG).
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def core() -> client.CoreV1Api:
    _load_config()
    return client.CoreV1Api()


def apps() -> client.AppsV1Api:
    _load_config()
    return client.AppsV1Api()


def custom() -> client.CustomObjectsApi:
    _load_config()
    return client.CustomObjectsApi()


# --- Secrets -------------------------------------------------------------------
def secret_bytes(ns: str, name: str, field: str) -> bytes:
    """Valeur decodee d'une cle de Secret (l'API renvoie .data en base64)."""
    data = core().read_namespaced_secret(name, ns).data or {}
    if field not in data:
        fail(f"cle {field} absente du Secret {ns}/{name}")
    return base64.b64decode(data[field])


def secret_value(ns: str, name: str, field: str) -> str:
    return secret_bytes(ns, name, field).decode()


def patch_secret(ns: str, name: str, values: dict[str, str]) -> None:
    """Remplace des cles d'un Secret (kubectl patch secret --type merge)."""
    data = {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}
    core().patch_namespaced_secret(name, ns, {"data": data})


# --- Pods ----------------------------------------------------------------------
def pod_by_label(ns: str, selector: str) -> str:
    """Nom du premier pod en cours d'execution correspondant au selecteur."""
    for p in core().list_namespaced_pod(ns, label_selector=selector).items:
        if p.status.phase == "Running" and p.metadata.deletion_timestamp is None:
            return p.metadata.name
    fail(f"aucun pod Running pour {ns}/{selector}")


def pod_exec(ns: str, pod: str, cmd: list[str], container: str | None = None) -> str:
    """kubectl exec : websocket vers pods/POD/exec (RBAC : create sur pods/exec)."""
    extra = {"container": container} if container else {}
    return stream(
        core().connect_get_namespaced_pod_exec, pod, ns,
        command=cmd, stdout=True, stderr=True, stdin=False, tty=False, **extra,
    )


def pod_logs_since(ns: str, pod: str, since: float) -> str:
    """Logs du pod depuis l'instant `since` (time.time()), avec 2 s de marge."""
    return core().read_namespaced_pod_log(pod, ns, since_seconds=int(time.time() - since) + 2)


def restart_count(ns: str, pod: str) -> int:
    return core().read_namespaced_pod(pod, ns).status.container_statuses[0].restart_count


def touch_pod(ns: str, pod: str, annotation: str) -> None:
    """Annote le pod : toute modification force kubelet a resynchroniser ses volumes."""
    core().patch_namespaced_pod(pod, ns, {"metadata": {"annotations": {annotation: stamp()}}})


# --- Deployments ---------------------------------------------------------------
def deployment_pod(ns: str, name: str) -> str:
    """Un pod du Deployment (equivalent de kubectl exec deploy/NAME)."""
    d = apps().read_namespaced_deployment(name, ns)
    selector = ",".join(f"{k}={v}" for k, v in d.spec.selector.match_labels.items())
    return pod_by_label(ns, selector)


def rollout_restart(ns: str, name: str) -> None:
    """kubectl rollout restart : modifie le template du pod -> nouveaux pods."""
    now = datetime.now(timezone.utc).isoformat()
    apps().patch_namespaced_deployment(
        name, ns,
        {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}},
    )


def rollout_status(ns: str, name: str, timeout: int = 300) -> None:
    """kubectl rollout status : attend que tous les pods soient neufs et prets."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = apps().read_namespaced_deployment(name, ns)
        want = d.spec.replicas if d.spec.replicas is not None else 1
        s = d.status
        if ((s.observed_generation or 0) >= d.metadata.generation  # le controleur a vu le patch
                and (s.updated_replicas or 0) == want               # tous les pods sont neufs
                and (s.replicas or 0) == want                       # plus d'anciens pods
                and (s.available_replicas or 0) == want):           # et ils sont prets
            return
        time.sleep(2)
    fail(f"rollout de deploy/{name} non termine en {timeout} s")
