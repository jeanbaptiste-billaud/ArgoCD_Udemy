"""Rotation d'une paire de cles S3 d'application, generique.

Deroule (chaque etape attend la fin de la precedente, arret a la premiere erreur) :
  1. nouvelle paire temporaire           (PushSecrets temporaires, generateurs ESO)
  2. lecture de la paire temporaire      (ExternalSecret temporaire)
  3. le backend S3 accepte les deux paires
  4. verification de la paire temporaire
  5. paire temporaire -> Secret officiel
  6. push officiel                       (PushSecret officiel)
  7. redemarrage de l'application, PUIS revocation de l'ancienne paire
  8. verifications finales
Les cles ne sont jamais affichees : seulement leurs empreintes.
"""
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pyESO import eso, kube
from pyESO.report import PyESOError, expect, fail, fp, log
from seaweedfs import SeaweedFS


@dataclass(frozen=True)
class Pair:
    access: str
    secret: str

    def __str__(self) -> str:
        return f"access {fp(self.access)} / secret {fp(self.secret)}"


@dataclass(frozen=True)
class S3KeyRotation:
    namespace: str
    bucket: str
    official_secret: str                    # Secret Kubernetes qui fait foi
    official_pushsecret: str                # Secret officiel -> OpenBao
    temp_pushsecrets: tuple[str, ...]       # generent la paire temporaire dans OpenBao
    temp_externalsecret: str                # paire temporaire OpenBao -> Secret
    temp_secret: str
    deployment: str                         # application qui consomme la paire
    container: str
    backend: SeaweedFS = field(default_factory=SeaweedFS)
    access_key_field: str = "AWS_ACCESS_KEY_ID"
    secret_key_field: str = "AWS_SECRET_ACCESS_KEY"
    # Verifications propres a l'application : (libelle, fonction -> code HTTP)
    app_checks: tuple[tuple[str, Callable[[], str]], ...] = ()

    # --- briques --------------------------------------------------------------
    def _read_pair(self, secret: str) -> Pair:
        return Pair(
            kube.secret_value(self.namespace, secret, self.access_key_field),
            kube.secret_value(self.namespace, secret, self.secret_key_field),
        )

    def _s3(self, pair: Pair) -> str:
        return self.backend.check(self.bucket, pair.access, pair.secret)

    def _check_app(self, when: str) -> None:
        for label, check in self.app_checks:
            expect(f"{label} ({when})", "200", check())

    # --- deroule --------------------------------------------------------------
    def preflight(self) -> Pair:
        """Etat de depart, lecture seule : la paire officielle et l'application fonctionnent."""
        official = self._read_pair(self.official_secret)
        log(f"Paire officielle de depart : {official}")
        expect("paire officielle de depart", "200", self._s3(official))
        self._check_app("depart")
        return official

    def run(self) -> None:
        ns = self.namespace
        old = self.preflight()

        log("1. Nouvelle paire temporaire")
        previous_temp = self._read_pair(self.temp_secret)
        for name in self.temp_pushsecrets:
            eso.trigger(ns, "pushsecret", name)

        log("2. Lecture de la paire temporaire")
        eso.trigger(ns, "externalsecret", self.temp_externalsecret)
        new = self._read_pair(self.temp_secret)
        if new.secret == previous_temp.secret:
            fail("la paire temporaire n'a pas change")
        log(f"  paire temporaire : {new}")

        log("3. Le backend S3 accepte les deux paires")
        self.backend.refresh_config()

        log("4. Verification")
        expect("paire temporaire", "200", self._s3(new))
        expect("paire officielle (encore valide)", "200", self._s3(old))

        log(f"5. Paire temporaire -> Secret officiel {self.official_secret}")
        kube.patch_secret(ns, self.official_secret,
                          {self.access_key_field: new.access, self.secret_key_field: new.secret})

        log("6. Push officiel")
        eso.trigger(ns, "pushsecret", self.official_pushsecret)

        # L'application d'abord : l'ancien pod sert jusqu'a ce que le nouveau soit pret
        # (maxSurge), il ne faut donc revoquer l'ancienne paire qu'apres.
        log(f"7. {self.deployment} sur la nouvelle paire, puis revocation de l'ancienne")
        kube.rollout_restart(ns, self.deployment)
        kube.rollout_status(ns, self.deployment)
        log(f"  {self.deployment} redemarre")
        self.backend.refresh_config()

        log("8. Verifications finales")
        expect("nouvelle paire officielle", "200", self._s3(new))
        expect("ancienne paire officielle (revoquee)", "403", self._s3(old))
        self._check_app("apres rotation")
        pod = kube.deployment_pod(ns, self.deployment)
        loaded = kube.pod_exec(ns, pod, ["printenv", self.access_key_field], container=self.container).strip()
        expect(f"cle d'acces chargee par {self.deployment}", fp(new.access), fp(loaded))


def main(rotation: S3KeyRotation, argv: list[str] | None = None) -> None:
    """Point d'entree des scripts d'application. --check : verifications seules, sans rien modifier."""
    argv = sys.argv[1:] if argv is None else argv
    start = time.monotonic()
    try:
        if "--check" in argv:
            rotation.preflight()
            log("Verifications OK (aucune modification)")
        else:
            rotation.run()
            log(f"Rotation terminee en {int(time.monotonic() - start)} s")
    except PyESOError as e:
        print(f"ECHEC : {e}", flush=True)
        sys.exit(1)
