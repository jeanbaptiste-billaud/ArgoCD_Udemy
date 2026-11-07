# ArgoCD_Udemy — branche `bento`

Code de l'application **predict** : une API qui estime le prix médian des logements d'un quartier californien (jeu de données *California housing* de scikit-learn). Branche **orpheline** : elle ne partage aucun historique avec les autres branches.

| Branche | Contenu | Qui la lit |
|---|---|---|
| `infra` | Manifests GitOps de la plateforme (dont le job de build `bento-build`) | ArgoCD |
| **`bento`** | Entraînement, service BentoML, préparation de l'image | **Clonée par le job de build** |
| `helm` | Chart umbrella `predict` + values `dev` / `recette` | ArgoCD (Applications `dev` et `recette`) |

## Contenu

```
train.py            # entraîne un modèle et l'enregistre dans le registre MLflow (alias @dev)
build_context.py    # MLflow -> store BentoML -> Bento -> contexte de build Docker + tag
service/
├── service.py      # service BentoML : /predict, /history, /info
└── bentofile.yaml  # dépendances de l'image (mêmes versions que uv.lock)
pyproject.toml      # projet uv
uv.lock             # versions figées
```

## Cycle de vie d'un modèle

```mermaid
flowchart LR
    T[train.py<br/>poste local] -->|version N + alias @dev| R[(Registre MLflow)]
    R -->|models:/california-housing@dev| B[Job bento-build<br/>build_context.py + BuildKit]
    B -->|push vN-sha| G[(ghcr.io/.../predict)]
    G -->|tag dans values-dev.yaml| D[Application dev]
    G -->|même tag, promu dans values-recette.yaml| RE[Application recette]
```

1. **Entraîner** depuis un poste qui voit MLflow (NodePort 30500). La nouvelle version reçoit l'alias `@dev` :
   ```bash
   export MLFLOW_TRACKING_URI=http://<IP>:30500
   uv run train.py --algo linear    # régression linéaire (+ standardisation)
   uv run train.py --algo gbr       # gradient boosting
   ```
2. **Construire l'image** de la version `@dev` (job `bento-build` de la branche `infra`) :
   ```bash
   kubectl -n bento-build create job --from=cronjob/predict-build predict-build-$(date +%s)
   kubectl -n bento-build logs -f job/<nom> --all-containers
   ```
   Tag produit : `v<version MLflow>-<commit de cette branche>`, ex. `ghcr.io/jeanbaptiste-billaud/predict:v2-1a2b3c4`.
3. **Déployer en dev** : reporter le tag dans `values-dev.yaml` (branche `helm`), commit, push.
4. **Promouvoir en recette** : reporter **le même tag** dans `values-recette.yaml`. L'image n'est pas reconstruite : la recette exécute exactement ce qui a été testé en dev.

Dev et recette exécutent donc des modèles différents tant qu'une version n'a pas été promue (ex. `gbr` v2 en dev, `linear` v1 en recette). `POST /info` indique le modèle servi.

## Le service

`service/service.py` — service BentoML `Predict` :

| Route | Entrée | Sortie |
|---|---|---|
| `POST /predict` | `{"houses": [{MedInc, HouseAge, AveRooms, AveBedrms, Population, AveOccup, Latitude, Longitude}]}` | prix estimé (centaines de k$) + modèle, par quartier |
| `POST /history` | `{"limit": 10}` | dernières prédictions journalisées |
| `POST /info` | `{}` | modèle servi, environnement |
| `GET /` | | Swagger UI de BentoML |
| `GET /livez`, `GET /readyz` | | sondes Kubernetes |

- **Le modèle est dans l'image** : l'API ne dépend pas de MLflow à l'exécution.
- **Journalisation PostgreSQL** si `PGHOST` est défini (variables libpq `PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`) : table `predictions` créée à la première écriture, pas au démarrage (l'API démarre même base coupée). Les écritures passent par un thread dédié : une base lente ou coupée ne retarde pas les prédictions, l'erreur est seulement loguée.
- `ENVIRONMENT` : nom de l'environnement, renvoyé par `/info`.

```bash
curl -s -X POST http://<IP>:<nodePort>/predict -H 'content-type: application/json' -d '{"houses":[{"MedInc":8.3,"HouseAge":41,"AveRooms":6.98,"AveBedrms":1.02,"Population":322,"AveOccup":2.56,"Latitude":37.88,"Longitude":-122.23}]}'
```

## Préparation de l'image (`build_context.py`)

`bentoml containerize` a besoin d'un démon Docker. Dans le cluster, le job sépare les deux moitiés :

1. `build_context.py` (image Python) importe `models:/california-housing@dev` dans le store BentoML, avec ses métadonnées (version MLflow, algorithme), construit le Bento, puis écrit le contexte de build complet (Bento + modèle + `env/docker/Dockerfile` généré) et `IMAGE_TAG`. Il réutilise la fonction interne de BentoML qui prépare ce contexte pour `containerize` (`bentoml._internal.container.construct_containerfile`) : à revérifier à chaque montée de version de BentoML.
2. BuildKit rootless construit ce contexte et pousse l'image sur GHCR.

## Pièges connus

- **Mêmes versions à l'entraînement et dans l'image** : MLflow 3 sérialise les modèles scikit-learn avec **skops** ; le modèle doit être relu avec les mêmes `scikit-learn` / `skops`. `service/bentofile.yaml` fige les versions de `uv.lock` : les mettre à jour ensemble.
- **skops et types de confiance** : skops refuse au chargement les types qu'il ne juge pas sûrs, dont `sklearn.tree._tree.Tree` (arbres, gradient boosting). `train.py` les déclare par algorithme (`TRUSTED_TYPES`) ; un nouvel algorithme à arbres doit y être ajouté.
- **`mlflow-skinny`** : client seul, même version que le serveur MLflow du cluster (3.16.0). Il ne sait pas écrire dans une base locale (`sqlite://`) : pour tester hors cluster, lancer un serveur `mlflow server --serve-artifacts`.

## Tester en local

```bash
uv sync
# serveur MLflow local (paquet mlflow complet, hors de ce projet)
uvx --from mlflow==3.16.0 mlflow server --port 5055 --serve-artifacts &
export MLFLOW_TRACKING_URI=http://127.0.0.1:5055 BENTOML_HOME=/tmp/bentoml
uv run train.py --algo gbr
uv run build_context.py --out /tmp/ctx --code-version local
docker build -t predict:local -f /tmp/ctx/env/docker/Dockerfile /tmp/ctx
docker run --rm -p 3000:3000 predict:local
```
