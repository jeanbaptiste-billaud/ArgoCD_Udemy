# ArgoCD_Udemy — branche `pyeso`

Outils Python de gestion des secrets du cluster. Branche **orpheline** : elle ne partage aucun historique avec `main` (manifests GitOps) ni `bootstrap` (installation).

| Branche | Contenu | Qui la lit |
|---|---|---|
| `main` | Manifests GitOps | ArgoCD |
| `bootstrap` | Scripts d'installation + `root-app.yaml` | Appliquée une fois à la main |
| **`pyeso`** | Package `pyESO` + scripts de rotation | **Clonée par les CronJobs** au démarrage |

## Contenu

```
pyESO/            # package générique (dépend de kubernetes)
├── report.py     # logs, empreintes, expect, PyESOError
├── kube.py       # API Kubernetes : Secrets, Pods (exec, logs), Deployments (rollout)
├── eso.py        # déclencher une synchro ExternalSecret / PushSecret et l'attendre
└── probe.py      # vérifications HTTP
s3_rotation/      # rotation des clés S3 (dépend de botocore), voir son README
├── rotation.py   # S3KeyRotation : déroulé en 8 étapes, main()
├── s3.py         # appel S3 signé (SigV4)
├── seaweedfs.py  # backend SeaweedFS : rechargement de la config par SIGHUP
└── rotate_mlflow.py
pyproject.toml    # projet uv (pyESO installable)
uv.lock           # versions figées des dépendances
```

## Exécution dans le cluster

Le CronJob `mlflow-s3-rotation` (`main:workloads/mlflow/s3/s3-rotation-cronjob.yaml`) :

1. un init container clone **cette branche** (`git clone --depth 1 --branch pyeso`) dans un `emptyDir` ;
2. le conteneur principal (image `ghcr.io/astral-sh/uv`) installe les dépendances de `uv.lock` et lance le script :

```bash
uv run --frozen --no-install-project s3_rotation/rotate_mlflow.py
```

Pas d'image à construire : un commit poussé sur `pyeso` est utilisé à la rotation suivante. `--frozen` garantit les versions de `uv.lock`.

## Exécution locale

```bash
uv sync
IP=<IP du nœud>
S3_ENDPOINT=http://$IP:30333 MLFLOW_URL=http://$IP:30500 uv run s3_rotation/rotate_mlflow.py --check
```

`--check` ne fait que des vérifications en lecture seule. Sans option, la rotation est complète.

Après un changement de dépendances (`pyproject.toml`), régénérer `uv.lock` (`uv lock`) et le commiter : le CronJob utilise `--frozen`.
