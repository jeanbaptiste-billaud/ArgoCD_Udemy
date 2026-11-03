"""SeaweedFS comme backend S3 : config d'identites generee par ESO, rechargee par SIGHUP."""
import hashlib
import re
import time
from dataclasses import dataclass

from pyESO import eso, kube
from s3 import s3_status
from pyESO.report import fail, log


@dataclass(frozen=True)
class SeaweedFS:
    namespace: str = "seaweedfs"
    endpoint: str = "http://seaweedfs-all-in-one.seaweedfs.svc:8333"
    config_externalsecret: str = "seaweedfs-s3-config"  # ExternalSecret qui genere la config
    config_secret: str = "seaweedfs-s3-config"          # Secret produit
    config_key: str = "seaweedfs_s3_config"             # cle du Secret = nom du fichier monte
    config_path: str = "/etc/sw/s3/seaweedfs_s3_config"  # fichier lu par weed (-s3.config)
    pod_selector: str = "app.kubernetes.io/name=seaweedfs"

    def check(self, bucket: str, access: str, secret: str) -> str:
        """Code HTTP d'un appel S3 signe avec cette paire."""
        return s3_status(self.endpoint, bucket, access, secret)

    def refresh_config(self) -> None:
        """Regenere la config d'identites depuis OpenBao, puis la recharge."""
        eso.trigger(self.namespace, "externalsecret", self.config_externalsecret)
        self.reload()

    def reload(self, timeout: float = 90) -> None:
        """Recharge la config sans redemarrage.

        Attend que kubelet ait mis a jour le fichier monte (meme empreinte que le
        Secret), puis envoie SIGHUP a weed (PID 1). Un SIGHUP trop tot relirait
        l'ancien fichier.
        """
        ns = self.namespace
        want = hashlib.sha256(kube.secret_bytes(ns, self.config_secret, self.config_key)).hexdigest()
        pod = kube.pod_by_label(ns, self.pod_selector)
        restarts = kube.restart_count(ns, pod)

        kube.touch_pod(ns, pod, "s3-config-sync")
        deadline = time.monotonic() + timeout
        while kube.pod_exec(ns, pod, ["sha256sum", self.config_path])[:64] != want:
            if time.monotonic() > deadline:
                fail(f"fichier de config non mis a jour dans le pod {pod}")
            time.sleep(1)

        since = time.time()
        kube.pod_exec(ns, pod, ["kill", "-HUP", "1"])
        time.sleep(1)
        if kube.restart_count(ns, pod) != restarts:
            fail(f"SeaweedFS a redemarre au lieu de recharger sa config ({pod})")
        if not re.search(r"Loaded \d+ identities from config file", kube.pod_logs_since(ns, pod, since)):
            fail("SeaweedFS n'a pas confirme le rechargement")
        log("  config SeaweedFS rechargee (SIGHUP, sans redemarrage)")
