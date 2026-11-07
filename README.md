# ArgoCD_Udemy

Lab GitOps d'un cluster Kubernetes local (MicroK8s sous WSL2), entièrement piloté par **ArgoCD** selon le pattern **app-of-apps**.

Le repo a **trois branches** :

| Branche | Contenu | Usage |
|---|---|---|
| **`bootstrap`** | Scripts d'installation (MicroK8s, ArgoCD) + `root-app.yaml` | Téléchargée une seule fois pour installer le cluster |
| **`main`** | Toutes les Applications et leur configuration | Seule source de vérité ensuite |
| **`pyeso`** | Outils Python : package `pyESO` + scripts de rotation (`s3_rotation/`), projet uv | Clonée au démarrage par les CronJobs (voir son README) |

Une fois le bootstrap effectué, **Git est la seule source de vérité** : toute modification du cluster passe par un commit sur `main`, qu'ArgoCD applique automatiquement. `main` ne dépend jamais de la branche `bootstrap`.

Composants déployés :

| Composant | Rôle | Namespace |
|---|---|---|
| **ArgoCD** | Moteur GitOps, se gère lui-même depuis ce repo | `argocd` |
| **External Secrets Operator (ESO)** | Synchronise des secrets externes vers des `Secret` Kubernetes | `external-secrets` |
| **OpenBao** | Coffre-fort de secrets (fork open source de Vault), en mode standalone (stockage persistant) | `openbao` |
| **SeaweedFS** | Stockage objet compatible S3 (mode all-in-one), stockage d'artefacts pour MLflow | `seaweedfs` |
| **PostgreSQL** | Serveur partagé : une base par application qui en a besoin (MLflow, …) | `postgres` |
| **MLflow** | Suivi d'expériences et registre de modèles ; artefacts dans SeaweedFS | `mlflow` |
| **kube-prometheus-stack** | Prometheus, Grafana, Alertmanager — **déploiement manuel** (voir plus bas) | `monitoring` |

---

## Sommaire

- [Architecture](#architecture)
- [Structure du repo](#structure-du-repo)
- [Description détaillée des fichiers](#description-détaillée-des-fichiers)
- [Installation depuis zéro](#installation-depuis-zéro)
- [Prérequis manuels (secrets)](#prérequis-manuels-secrets)
- [Accès aux interfaces](#accès-aux-interfaces)
- [Ordre de déploiement (sync waves)](#ordre-de-déploiement-sync-waves)
- [Opérations courantes](#opérations-courantes)
- [Choix techniques et pièges connus](#choix-techniques-et-pièges-connus)
- [Sécurité](#sécurité)
- [Sources](#sources)

---

## Architecture

```mermaid
flowchart TD
    subgraph manuel["Branche bootstrap — appliqué une seule fois à la main"]
        RA[root-app.yaml]
    end

    RA --> ROOT[Application<br/>root]

    ROOT -->|synchronise main:apps/ récursivement| RP[Application<br/>root-projects]
    RP -->|synchronise projects/| PRJ[AppProject<br/>infra]

    ROOT --> ARGO[Application<br/>argocd]
    ROOT --> ESO[Application<br/>external-secrets-operator]
    ROOT --> ESOC[Application<br/>eso-config]
    ROOT --> BAO[Application<br/>openbao]
    ROOT --> SWFS[Application<br/>seaweedfs]
    ROOT --> PG[Application<br/>postgres]
    ROOT --> MLF[Application<br/>mlflow]
    ROOT --> RLD[Application<br/>reloader]
    ROOT -. exclu .-> PROM[Application<br/>prometheus]

    ARGO -->|chart argo-cd + values| ARGOCD[(ArgoCD)]
    ESO -->|chart external-secrets| ESOD[(ESO)]
    ESOC -->|workloads/eso-config| CSS[(ClusterSecretStore)]
    BAO -->|chart openbao| BAOD[(OpenBao)]
    SWFS -->|chart seaweedfs + workloads/seaweedfs| SWFSD[(SeaweedFS S3)]
    PG -->|workloads/postgres| PGD[(PostgreSQL)]
    MLF -->|chart mlflow + workloads/mlflow| MLFD[(MLflow)]
    MLFD -->|base mlflow| PGD
    MLFD -->|artefacts s3://mlflow| SWFSD
    RLD -->|chart reloader| RLDD[(Reloader)]
    RLDD -.->|redémarre sur rotation du Secret Postgres| MLFD
    PROM -.->|chart kube-prometheus-stack| PROMD[(Monitoring)]

    CSS -->|lit les secrets| BAOD
    SWFSD -.->|identifiants S3 via ESO| CSS
```

Points clés :

- **`root-app.yaml` (branche `bootstrap`) est le seul fichier appliqué à la main.** Il crée l'Application racine **`root`**, qui synchronise `main:apps/`. Tout le reste en découle :
  - `root-projects` (définie dans `apps/root-projects/`) → synchronise `projects/` (les **AppProjects**) ;
  - les autres fichiers de `apps/` → toutes les **Applications** plateforme.
- **`root` n'est pas surveillée par ArgoCD** : ajouter une app ne demande aucune action sur la branche `bootstrap`. On ne réapplique `root-app.yaml` que pour modifier `root` elle-même.
- **ArgoCD se gère lui-même** : l'Application `argocd` reprend la release Helm installée par le script de bootstrap, avec les values de `manifests/argocd/values.yaml`.
- Chaque composant est une **Application séparée** (une « tuile » dans l'UI ArgoCD), ce qui permet de les synchroniser, diagnostiquer ou supprimer indépendamment.

---

## Structure du repo

Branche **`bootstrap`** (voir son propre README) :

```
├── README.md
├── install_kub_microk8s.sh            # 1. installe MicroK8s sous WSL2
├── install_ArgoCD.sh                  # 2. installe ArgoCD (Helm) + CLI + applique root-app.yaml
├── argocd-values.yaml                 # values Helm MINIMALES du premier install
└── root-app.yaml                      # 3. point d'entrée GitOps : Application "root" -> main:apps/
```

Branche **`main`** :

```
ArgoCD_Udemy/
├── README.md                          # ce fichier
├── projects/                          # AppProjects — synchronisé par root-projects
│   └── infra-project.yaml             # AppProject "infra" (droits des apps plateforme)
├── apps/                              # Applications ArgoCD — synchronisé par root (récursif)
│   ├── root-projects/
│   │   └── application.yaml           # synchronise projects/ (wave -1)
│   └── platform/                      # composants d'infrastructure
│       ├── argocd/
│       │   └── application.yaml       # ArgoCD qui se gère lui-même
│       ├── external-secret-operator/
│       │   ├── operator/
│       │   │   └── application.yaml   # l'opérateur ESO (chart Helm)
│       │   └── config/
│       │       └── application.yaml   # pointe vers workloads/eso-config
│       ├── openbao/
│       │   └── application.yaml       # OpenBao (chart Helm, mode standalone)
│       ├── seaweedfs/
│       │   └── application.yaml       # SeaweedFS S3 (chart Helm all-in-one + ExternalSecret)
│       ├── postgres/
│       │   └── application.yaml       # PostgreSQL partagé (serveur + une base par appli)
│       ├── mlflow/
│       │   └── application.yaml       # MLflow (chart Helm + manifests)
│       ├── reloader/
│       │   └── application.yaml       # Reloader : redémarre les applis quand leurs Secrets changent
│       └── prometheus/
│           └── application.yaml       # kube-prometheus-stack — EXCLU de root
├── manifests/                         # values Helm référencées par des Applications ($values)
│   ├── argocd/
│   │   └── values.yaml                # values complètes d'ArgoCD
│   ├── openbao/
│   │   └── values.yaml
│   ├── seaweedfs/
│   │   └── values.yaml
│   └── mlflow/
│       └── values.yaml
├── workloads/                         # manifests "bruts" référencés par des Applications
│   ├── eso-config/
│   │   ├── cluster-secret-store.yaml  # ClusterSecretStore OpenBao (KV v2 "secret")
│   │   └── cluster-secret-store-database.yaml # ClusterSecretStore OpenBao (moteur "database")
│   ├── seaweedfs/
│   │   ├── s3-credentials.yaml        # ExternalSecret : config S3 de SeaweedFS depuis OpenBao
│   │   └── s3-nodeport.yaml           # Service NodePort 30333 (S3 uniquement)
│   ├── postgres/
│   │   ├── admin-credentials.yaml     # ExternalSecret du superutilisateur
│   │   ├── service.yaml               # Service postgres.postgres.svc:5432
│   │   ├── statefulset.yaml           # serveur PostgreSQL
│   │   └── databases/                 # 1 dossier par application qui a besoin d'une base
│   │       └── mlflow/
│   │           └── create-db-job.yaml # Job : rôle et base "mlflow" (mot de passe géré par OpenBao)
│   └── mlflow/
│       ├── postgres-credentials.yaml  # ExternalSecret : accès à la base mlflow
│       ├── nodeport.yaml              # Service NodePort 30500
│       └── s3/
│           ├── s3-generators.yaml     # Generators Password : access key + secret key
│           ├── s3-bootstrap-pushsecret.yaml # 2 PushSecrets : paire officielle générée -> OpenBao (une seule fois)
│           ├── s3-credentials.yaml    # ExternalSecret : OpenBao -> Secret Kubernetes (une seule fois)
│           ├── s3-pushsecret.yaml     # PushSecret : Secret Kubernetes -> OpenBao
│           ├── s3-temp-pushsecret.yaml # 2 PushSecrets : paire temporaire générée -> OpenBao (rotation)
│           ├── s3-temp-credentials.yaml # ExternalSecret : paire temporaire OpenBao -> Secret mlflow-s3-temp
│           ├── s3-rotation-rbac.yaml  # ServiceAccount + Roles (mlflow, seaweedfs) du job de rotation
│           └── s3-rotation-cronjob.yaml # CronJob de rotation mensuelle (code : branche pyeso)
└── roar-k8s-helm.yaml                 # exercice du cours, NON géré par le GitOps
```

### Logique de découpage

| Dossier | Contient | Synchronisé par | Règle |
|---|---|---|---|
| branche `bootstrap` | Scripts d'installation + point d'entrée | appliqué à la main, une fois | Ne contient que ce qui est nécessaire *avant* qu'ArgoCD tourne |
| branche `pyeso` | Code Python exécuté par les CronJobs | cloné par le CronJob à chaque exécution | Branche orpheline : pas de code applicatif sur `main` |
| `projects/` | Uniquement des `AppProject` | `root-projects` | Un fichier par projet |
| `apps/` | Uniquement des `Application` ArgoCD | `root` (récursif) | Un dossier par composant, un fichier `application.yaml`. **Aucun autre YAML** (sinon `root` essaie de l'appliquer) |
| `manifests/` | Fichiers de values Helm | lus via `$values` par une Application | Jamais synchronisé directement |
| `workloads/` | Manifests Kubernetes classiques | une Application de `apps/` qui pointe dessus | Jamais synchronisé directement par une app racine. **Un fichier par rôle fonctionnel** (plusieurs ressources possibles) |

> ⚠️ Un objet Kubernetes ne doit être défini **qu'à un seul endroit**. Si deux Applications gèrent le même objet, elles le réécrivent chacune leur tour et passent en OutOfSync en boucle (c'est arrivé avec l'AppProject `infra`, voir [Pièges connus](#choix-techniques-et-pièges-connus)).

---

## Description détaillée des fichiers

### Branche `bootstrap`

Décrite en détail dans le README de la branche. En résumé :

- **`install_kub_microk8s.sh`** — installe MicroK8s sous WSL2 (⚠️ désactiver d'abord l'intégration Docker Desktop), addons `dns`, `storage`, `dashboard`, alias `kubectl`/`helm`.
- **`install_ArgoCD.sh`** — `helm install` du chart `argo-cd` **10.1.3** (release `argocd`) avec des values **minimales**, installe la CLI `argocd` **v3.4.5**, se connecte, puis applique `root-app.yaml`.
- **`argocd-values.yaml`** — values minimales du premier install (NodePort `30080`, HTTP). Pas de `ServiceMonitor` : leur CRD n'existe pas encore.
- **`root-app.yaml`** — Application racine **`root`** (projet `default`) : synchronise `main:apps/` récursivement, exclut `platform/prometheus/*`, `prune` + `selfHeal`, finalizer.

> ⚠️ `root` a `prune: true` et un finalizer : **supprimer ou exclure un fichier de `apps/` supprime l'Application correspondante et toutes les ressources qu'elle a déployées**. Supprimer `root` elle-même supprimerait tout le cluster applicatif.

> Le nom de release `argocd` et la version `10.1.3` doivent rester **identiques** entre `install_ArgoCD.sh` et `apps/platform/argocd/application.yaml`, sinon ArgoCD installerait une seconde copie de lui-même au lieu de reprendre la release existante.

### `apps/root-projects/application.yaml`

Application **`root-projects`** (sync-wave `-1`) :
- Synchronise `projects/` (récursif) dans le namespace `argocd`.
- Appartient au projet **`default`** : elle ne peut pas appartenir à `infra` puisque c'est elle qui crée `infra` (problème de l'œuf et de la poule sur un cluster neuf).
- `automated` avec `prune` + `selfHeal`, `ServerSideApply`.
- Annotation `Delete=false` : protège l'Application contre une suppression en cascade.

### `manifests/argocd/values.yaml`

Values Helm **complètes** d'ArgoCD, lues par l'Application `argocd` via la référence `$values`. Modifier ce fichier et pousser suffit à reconfigurer ArgoCD.

| Paramètre | Valeur | Effet |
|---|---|---|
| `server.service.type` / `nodePorts.http` | `NodePort` / `30080` | UI et API ArgoCD accessibles sur `http://<IP-noeud>:30080` |
| `server.insecure` (`configs.params`) | `true` | ArgoCD sert en HTTP (pas de TLS) — acceptable pour un lab local |
| `*.metrics.enabled` | `true` | Expose les métriques de `server`, `controller` et `repoServer` |
| `*.metrics.serviceMonitor.enabled` | `true` | Crée des `ServiceMonitor` pour que Prometheus scrape ArgoCD |
| `serviceMonitor.additionalLabels.release` | `prometheus` | Label attendu par le sélecteur de kube-prometheus-stack (release `prometheus`) |

### `projects/infra-project.yaml`

AppProject **`infra`**, utilisé par toutes les Applications plateforme. Il définit ce qu'elles ont le droit de faire :

- **`sourceRepos`** — d'où elles peuvent tirer leurs manifests :
  - ce repo Git ;
  - `https://argoproj.github.io/argo-helm` (chart ArgoCD) ;
  - `https://charts.external-secrets.io` (chart ESO) ;
  - `https://openbao.github.io/openbao-helm` (chart OpenBao) ;
  - `https://seaweedfs.github.io/seaweedfs/helm` (chart SeaweedFS) ;
  - `https://community-charts.github.io/helm-charts` (chart MLflow) ;
  - `https://stakater.github.io/stakater-charts` (chart Reloader) ;
  - `ghcr.io/prometheus-community/charts` (chart OCI kube-prometheus-stack).
- **`destinations`** — où elles peuvent déployer : `argocd`, `external-secrets`, `openbao`, `seaweedfs`, `postgres`, `mlflow`, `reloader`, `monitoring`, `kube-system` (certains charts y posent des composants, ex. Services de kubelet pour Prometheus).
- **`clusterResourceWhitelist: */*`** — autorise les ressources cluster-scoped (CRDs, ClusterRoles, webhooks…), nécessaires aux opérateurs.
- Annotation `Delete=false` : l'AppProject n'est jamais supprimé en cascade, même si `root-projects` l'est.

> Pour un **nouveau composant** utilisant un nouveau repo Helm ou un nouveau namespace, il faut l'ajouter ici, sinon ArgoCD refuse la synchronisation (`application destination ... is not permitted in project`).

### `apps/platform/argocd/application.yaml`

Application **`argocd`** — ArgoCD qui se gère lui-même (sync-wave `-1`). Utilise **deux sources** :

1. le chart Helm `argo-cd` 10.1.3, release `argocd`, avec `$values/manifests/argocd/values.yaml` ;
2. ce repo Git (branche `main`), référencé sous le nom `values` (sert uniquement à lire le fichier de values ci-dessus).

Choix de prudence :
- **Pas de finalizer** : supprimer cette Application ne désinstalle ni ArgoCD ni le reste du cluster.
- **`prune: false`** : ArgoCD ne supprime jamais automatiquement ses propres ressources.
- `selfHeal: true` : toute modification manuelle d'ArgoCD est annulée.
- `ServerSideApply=true` : les CRDs d'ArgoCD sont trop volumineuses pour un apply client-side (limite de taille de l'annotation `last-applied-configuration`).
- `SkipDryRunOnMissingResource=true` : permet de synchroniser les `ServiceMonitor` même si la CRD est absente (Prometheus non installé).

### `apps/platform/external-secret-operator/operator/application.yaml`

Application **`external-secrets-operator`** (sync-wave `0`) — installe le chart `external-secrets` **2.13.0** dans `external-secrets`.

- Pas de `releaseName` : la release prend le nom de l'Application (`external-secrets-operator`), d'où les noms de ressources `external-secrets-operator-*`.
- **`ignoreDifferences` sur `.webhooks[].clientConfig.caBundle`** des `ValidatingWebhookConfiguration` + `RespectIgnoreDifferences=true` : le cert-controller d'ESO injecte lui-même le certificat de sa CA dans ses webhooks. Sans ça, ArgoCD voit une dérive et le réécrit en boucle (voir [Pièges connus](#choix-techniques-et-pièges-connus)).
- `prune` + `selfHeal`, `CreateNamespace`, `ServerSideApply`.

### `apps/platform/external-secret-operator/config/application.yaml`

Application **`eso-config`** (sync-wave `1`, donc **après** l'opérateur) — déploie `workloads/eso-config/` (destination `external-secrets` ; le `ClusterSecretStore` est cluster-scoped).

- Séparée de l'opérateur car elle crée un `ClusterSecretStore`, dont la **CRD est installée par l'opérateur**.
- `SkipDryRunOnMissingResource=true` + **`retry`** (10 tentatives, backoff 30 s → 5 min) : au tout premier passage, les CRDs ESO peuvent ne pas encore exister ; ArgoCD réessaie jusqu'à ce qu'elles soient là.

### `apps/platform/openbao/application.yaml`

Application **`openbao`** (sync-wave `0`) — chart `openbao` **0.30.3** dans `openbao`.

Deux sources : le chart, et ce repo (`ref: values`) pour lire `manifests/openbao/values.yaml`.

- **Mode standalone** : un seul pod, stockage intégré **Raft** (mono-nœud) persistant sur un PVC (`microk8s-hostpath`, monté sur `/openbao/data`), HTTP sans TLS, UI activée.
- Au premier démarrage, OpenBao est **non initialisé et scellé (sealed)**. Il faut l'initialiser une fois, puis le **déverrouiller (unseal) après chaque redémarrage du pod**. Voir [Prérequis manuels](#prérequis-manuels-secrets).
- Tant qu'il est scellé, le pod reste `0/1` et l'Application n'est pas *Healthy* : c'est normal.
- Agent injector désactivé (`injector.enabled: false`), donc pas de webhook ni de `ignoreDifferences`.
- Service exposé en **NodePort 30200**.
- `selfHeal: false`.

### `apps/platform/seaweedfs/application.yaml`

Application **`seaweedfs`** (sync-wave `2`) — chart officiel `seaweedfs` **4.51.0** (la 4.52.0 référence une image `4.52` non publiée sur Docker Hub) dans `seaweedfs`, stockage S3 des artefacts MLflow.

Trois sources : le chart, ce repo (`ref: values`) pour `manifests/seaweedfs/values.yaml`, et ce repo (`path: workloads/seaweedfs`) pour l'`ExternalSecret` des identifiants S3 et le Service NodePort S3.

- **Mode all-in-one** (`manifests/seaweedfs/values.yaml`) : un seul pod `weed server` (master + volume + filer + passerelle S3). `master`, `volume` et `filer` séparés sont désactivés.
- Données persistées sur un PVC `seaweedfs-all-in-one-data` (10 Gi, `microk8s-hostpath`).
- S3 sur le port **8333**, authentification activée. Le Service du chart (`seaweedfs-all-in-one.seaweedfs.svc`) est en **ClusterIP** : en NodePort, Kubernetes attribuerait un NodePort aléatoire à **chaque** port (master, volume, filer…), et le filer (8888) permet de lire et supprimer les fichiers **sans authentification**. Seul S3 est exposé, en **NodePort 30333**, par `workloads/seaweedfs/s3-nodeport.yaml`.
- Interfaces web (master 9333, filer 8888) : accès ponctuel par `kubectl -n seaweedfs port-forward svc/seaweedfs-all-in-one 9333 8888`.
- Bucket **`mlflow`** créé par le Job `seaweedfs-bucket-hook` (hook Helm `post-install`, exécuté par ArgoCD en **PostSync**, idempotent).
- Wave `2` + `SkipDryRunOnMissingResource` + `retry` : a besoin des CRDs ESO et du `ClusterSecretStore` `openbao-backend`.
- Tant que le Secret `seaweedfs-s3-config` n'existe pas (OpenBao scellé ou secret absent), le pod reste en `ContainerCreating` : c'est normal.

### `workloads/seaweedfs/s3-credentials.yaml`

`ExternalSecret` `seaweedfs-s3-config` (namespace `seaweedfs`) : génère (via un `template` ESO) la clé `seaweedfs_s3_config`, au format JSON d'identités attendu par `weed s3 -config`. Deux identités :

| Identité | Clés lues dans OpenBao | Droits |
|---|---|---|
| `admin` | `secret/seaweedfs/admin` | `Admin`, `Read`, `Write`, `List`, `Tagging` sur tous les buckets |
| `mlflow` | `secret/seaweedfs/s3` : paire officielle (`accessKey` / `secretKey`) **et** paire temporaire de rotation (`tempAccessKey` / `tempSecretKey`) | `Read`, `Write`, `List`, `Tagging` sur le bucket `mlflow` uniquement (`Read:mlflow`…) |

L'identité `mlflow` a **deux credentials** : pendant une rotation, l'ancienne et la nouvelle paire sont valides en même temps, ce qui permet de tester la nouvelle avant de basculer MLflow. Après la rotation, les deux paires sont identiques.

La config est lue au démarrage de SeaweedFS, et peut être **rechargée sans redémarrage** par un `SIGHUP` au process `weed` (PID 1 du conteneur). Quand `-s3.config` est défini, SeaweedFS relit le fichier sur ce signal (`weed/s3api/s3api_server.go`) et logue `Loaded N identities from config file …`. Après une modification (fichier ou clés dans OpenBao) :

1. rafraîchir l'`ExternalSecret` `seaweedfs-s3-config` (ou attendre son refresh, ≤ 1 h) ;
2. attendre que kubelet ait mis à jour le fichier monté dans le pod : de quelques secondes à environ 1 min. Le Secret est monté **sans `subPath`**, condition nécessaire à cette mise à jour. Pour le vérifier, comparer `sha256sum /etc/sw/s3/seaweedfs_s3_config` dans le pod avec le contenu du Secret ;
3. envoyer le signal :

```bash
kubectl -n seaweedfs exec deploy/seaweedfs-all-in-one -- kill -HUP 1
```

Un `SIGHUP` envoyé trop tôt recharge l'ancienne version du fichier. Redémarrer le pod (`kubectl -n seaweedfs rollout restart deploy/seaweedfs-all-in-one`) fonctionne aussi, mais coupe S3 quelques dizaines de secondes (un seul pod all-in-one).

> Pourquoi pas la configuration **Filer-based** ([S3 Credentials](https://github.com/seaweedfs/seaweedfs/wiki/S3-Credentials)), elle aussi rechargée à chaud ? Le fichier `-s3.config` a priorité et **remplace entièrement** la config du filer, sans fusion. Il faudrait donc retirer `-s3.config`, gérer les identités avec `weed shell`, et la source de vérité quitterait OpenBao.

Lister les identités réellement chargées (clés masquées) :

```bash
kubectl -n seaweedfs exec deploy/seaweedfs-all-in-one -- sh -c 'echo s3.configure | weed shell' \
  | sed -E 's/("(access|secret)Key": ")[^"]*/\1***/'
```

`s3.configure` sans `-apply` ne modifie rien. Ne pas créer d'identités avec `s3.configure -apply` : elles vivraient dans le filer, hors GitOps.

> Pourquoi pas les identifiants générés par le chart ? Son Secret S3 utilise `lookup` + `randAlphaNum` pour conserver des clés aléatoires entre deux `helm upgrade`. **ArgoCD ne supporte pas `lookup`** (il fait un `helm template`) : les clés seraient régénérées à chaque sync. D'où `existingConfigSecret`.

### `workloads/seaweedfs/s3-nodeport.yaml`

`Service` `seaweedfs-s3-nodeport` : expose uniquement le port S3 (8333) du pod all-in-one en **NodePort 30333**.

### `apps/platform/postgres/application.yaml`

Application **`postgres`** (sync-wave `2`) — déploie `workloads/postgres/` **récursivement** (donc `databases/` inclus) dans `postgres`. Pas de chart : les charts Bitnami ne sont plus maintenus en libre accès, l'image officielle `postgres:17` suffit.

### `workloads/postgres/` (serveur)

- **`admin-credentials.yaml`** — `ExternalSecret` `postgres-admin` : superutilisateur (`username` / `password`) lu dans OpenBao `secret/postgres/admin`.
- **`statefulset.yaml`** — `StatefulSet` `postgres` : 1 réplica, données sur un PVC de 10 Gi (`microk8s-hostpath`), `PGDATA` dans un sous-dossier, sondes `pg_isready`.
- **`service.yaml`** — `Service` `postgres` (ClusterIP) : `postgres.postgres.svc:5432` depuis tout le cluster.

> `POSTGRES_USER` / `POSTGRES_PASSWORD` ne sont lus **qu'à l'initialisation** du volume : changer le mot de passe admin dans OpenBao ensuite ne change pas celui de la base (il faut aussi un `ALTER ROLE`).

### `workloads/postgres/databases/<appli>/`

**Un dossier par application qui a besoin d'une base**, avec un fichier :

- **`create-db-job.yaml`** — `Job` `db-<appli>`, hook ArgoCD **`PostSync`** : se connecte en superutilisateur et, de façon idempotente, crée le rôle s'il n'existe pas (**sans mot de passe**), le délègue au rôle `openbao` (`GRANT <appli> TO openbao WITH ADMIN OPTION`), crée la base `<appli>` si elle n'existe pas et en donne la propriété au rôle.

**Le mot de passe appartient à OpenBao** : le moteur `database` gère le rôle via un **static role** `<appli>-role` (nom d'utilisateur fixe, mot de passe changé par OpenBao toutes les `rotation_period`). Le Job n'y touche jamais : s'il réappliquait un mot de passe à chaque sync, il écraserait celui d'OpenBao. Le nom d'utilisateur fixe garde aussi la propriété des tables créées par l'appli (avec des utilisateurs dynamiques, chaque migration créerait des tables appartenant à un utilisateur jetable).

L'application cliente lit les identifiants via un `ExternalSecret` sur le store `openbao-database` (`static-creds/<appli>-role`), dans son namespace (ex. `workloads/mlflow/postgres-credentials.yaml`), et se connecte à `postgres.postgres.svc:5432`.

### `apps/platform/mlflow/application.yaml`

Application **`mlflow`** (sync-wave `3`) — chart `mlflow` **1.11.7** de community-charts (MLflow **3.16.0**) dans `mlflow`.

Trois sources : le chart, ce repo (`ref: values`) pour `manifests/mlflow/values.yaml`, et ce repo (`path: workloads/mlflow`, récursif pour inclure `s3/`).

- Image `burakince/mlflow` : contrairement à l'image officielle, elle embarque `psycopg2` (PostgreSQL) et `boto3` (S3).
- **Métadonnées** dans la base `mlflow` du PostgreSQL partagé (`backendStore.postgres` + `existingDatabaseSecret`). Deux init containers : l'un attend que Postgres réponde, l'autre crée/migre le schéma.
- **Artefacts** dans `s3://mlflow` sur SeaweedFS (`MLFLOW_S3_ENDPOINT_URL`), en **mode proxy** (`--serve-artifacts`) : les clients envoient leurs artefacts à MLflow, qui les écrit dans S3. Les clients n'ont besoin ni des identifiants S3 ni d'un accès à SeaweedFS.
- `serverAllowedHosts: ["*"]` : MLflow 3 rejette les requêtes dont l'en-tête `Host` n'est pas autorisé (403). Sans ça, l'accès par `<IP>:30500` ou par le nom DNS du Service échouerait.
- Service du chart en ClusterIP (`mlflow.mlflow.svc:80`) ; accès externe par le Service `mlflow-nodeport` (**NodePort 30500**), car le chart ne permet pas de fixer le `nodePort`.
- Pas d'authentification MLflow (`auth.enabled: false`).

`workloads/mlflow/` contient :
- **`postgres-credentials.yaml`** — `ExternalSecret` `mlflow-postgres-credentials` : `username` / `password` du static role `mlflow-role`, lus via le store `openbao-database` (`database/static-creds/mlflow-role`). Rafraîchi toutes les 5 min pour suivre les rotations d'OpenBao (toutes les 24 h). MLflow lit ces identifiants en variables d'environnement, **au démarrage seulement** : l'annotation `secret.reloader.stakater.com/reload: mlflow-postgres-credentials` (`deploymentAnnotations` des values) fait redémarrer le pod par [Reloader](#appsplatformreloaderapplicationyaml) dès que le Secret change. Entre la rotation et le rafraîchissement du Secret (≤ 5 min), les nouvelles connexions de MLflow échouent ;
- **`nodeport.yaml`** — `Service` `mlflow-nodeport` (NodePort 30500) ;
- **`s3/`** — clés S3 de l'identité `mlflow` de SeaweedFS (voir ci-dessous).

**Clés S3 de MLflow : le Secret Kubernetes fait foi.** Elles sont destinées à être renouvelées depuis le cluster (rotation mensuelle par un CronJob), d'où ce circuit :

0. **`s3/s3-generators.yaml`** — deux générateurs ESO `Password` : `mlflow-s3-access-key` (20 caractères) et `mlflow-s3-secret-key` (40 caractères), alphanumériques. En S3, l'access key n'est qu'un identifiant, transmis en clair dans chaque requête ; c'est la secret key, qui signe les requêtes (SigV4) sans jamais circuler, qui protège l'accès. Ils servent à la paire officielle (étape 1) et à la paire temporaire (étape 5).
1. **`s3/s3-bootstrap-pushsecret.yaml`** — PushSecrets `mlflow-s3-bootstrap-access-push` et `mlflow-s3-bootstrap-secret-push` (un par générateur) : écrivent la paire **officielle** `accessKey` / `secretKey` dans `secret/seaweedfs/s3`. Aucune clé `mlflow` ne passe entre des mains humaines. `updatePolicy: IfNotExists` : chaque propriété n'est écrite que si elle est absente, ces PushSecrets n'écrasent **jamais** la paire officielle. `refreshInterval: 0s` : un seul passage, à leur création. Si le chemin n'existe pas, ESO le crée avec la métadonnée `managed-by=external-secrets`, ce qui autorise les autres PushSecrets à y écrire.
2. **`s3/s3-credentials.yaml`** — `ExternalSecret` `mlflow-s3-credentials`, `refreshPolicy: CreatedOnce` : crée **une seule fois** le Secret `mlflow-s3-credentials` (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) depuis OpenBao `secret/seaweedfs/s3`, puis ne le modifie plus. `creationPolicy: Orphan` : le Secret survit à la suppression de l'`ExternalSecret`.
3. **`s3/s3-pushsecret.yaml`** — `PushSecret` `mlflow-s3-credentials-push` : renvoie ce Secret vers `secret/seaweedfs/s3` (`accessKey` / `secretKey`), les **mêmes** emplacements qu'à l'étape 2. Il ne génère **rien** : il recopie seulement le Secret Kubernetes. `deletionPolicy: None` : supprimer le PushSecret ne supprime rien dans OpenBao.
4. SeaweedFS lit `secret/seaweedfs/s3` pour son identité `mlflow` (`workloads/seaweedfs/s3-credentials.yaml`).
5. **`s3/s3-temp-pushsecret.yaml`** — PushSecrets `mlflow-s3-temp-access-push` et `mlflow-s3-temp-secret-push` (un par générateur) : écrivent la paire **temporaire** `tempAccessKey` / `tempSecretKey` dans `secret/seaweedfs/s3`, à côté de la paire officielle sans l'écraser. C'est **la seule source de nouvelles clés** pour la rotation. Aucun Secret Kubernetes intermédiaire : la paire temporaire n'existe que dans OpenBao. `updatePolicy: Replace` + nouvelle génération à chaque push : **chaque déclenchement remplace la paire temporaire par une nouvelle**, sans interaction directe avec OpenBao. Toujours déclencher les **deux** ensemble, sinon on obtient une access key neuve avec une secret key ancienne.
6. **`s3/s3-temp-credentials.yaml`** — `ExternalSecret` `mlflow-s3-temp` : recopie la paire temporaire dans le Secret `mlflow-s3-temp` (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, mêmes noms que le Secret officiel), pour que le job de rotation la lise sans accès direct à OpenBao. Les PushSecrets générés ne créent **aucun** Secret Kubernetes : la valeur générée n'existe qu'en mémoire le temps du push. `refreshPolicy: OnChange` : mis à jour uniquement quand l'ExternalSecret change (annotation comprise), à déclencher **après** la fin des push temporaires.

**Rotation : `s3/s3-rotation-cronjob.yaml`** — CronJob `mlflow-s3-rotation`, le 1er de chaque mois à 03:00 (Europe/Paris). Le code vient de la branche **`pyeso`**, sans image à construire : un init container `alpine/git` la clone (`--depth 1`) dans un `emptyDir`, puis le conteneur principal (image `ghcr.io/astral-sh/uv`, Python 3.14) installe les dépendances figées par `uv.lock` et lance `s3_rotation/rotate_mlflow.py` (`uv sync --frozen --no-install-project`, puis le Python du venv ; `pyESO` est importé via `PYTHONPATH`). Un commit poussé sur `pyeso` est utilisé à la rotation suivante. Le pod doit pouvoir joindre GitHub et PyPI. Étapes, chacune attendant la fin de la précédente (fin de synchro ESO : `status.refreshTime` modifié et `Ready=True`), arrêt à la première erreur :

1. déclencher les deux PushSecrets temporaires (étape 5) : nouvelle paire temporaire dans OpenBao ;
2. déclencher l'ExternalSecret `mlflow-s3-temp` (étape 6) et lire le Secret `mlflow-s3-temp` ;
3. SeaweedFS accepte les deux paires : rafraîchir `seaweedfs-s3-config`, puis recharger par `SIGHUP` (voir [SeaweedFS](#workloadsseaweedfss3-credentialsyaml)). Le script annote le pod SeaweedFS : modifier le pod force kubelet à resynchroniser ses volumes tout de suite (1 à 2 s au lieu d'une minute environ) ;
4. vérifier la paire temporaire (appel S3 signé), et que l'ancienne fonctionne toujours ;
5. l'écrire dans le Secret officiel `mlflow-s3-credentials` ;
6. déclencher `mlflow-s3-credentials-push` : la paire officielle dans OpenBao prend les valeurs temporaires ;
7. redémarrer MLflow, qui lit ses clés en variables d'environnement, **puis** révoquer l'ancienne paire (nouveau `SIGHUP`). Dans cet ordre, car avec `maxSurge: 100%` l'ancien pod MLflow sert jusqu'à ce que le nouveau soit prêt : révoquer avant le casserait pendant ce temps ;
8. vérifier : nouvelle paire 200, ancienne 403, API d'artefacts de MLflow 200, clé chargée par le pod MLflow.

Les clés ne sont jamais affichées : les logs ne montrent que des empreintes sha256. Durée mesurée : environ 70 s, sans coupure de S3 ni de MLflow.

```bash
# Lancer une rotation à la main
kubectl -n mlflow create job --from=cronjob/mlflow-s3-rotation mlflow-s3-rotation-manual
kubectl -n mlflow logs -f job/mlflow-s3-rotation-manual
```

`backoffLimit: 0` : pas de relance automatique. Le script n'est pas rejouable à l'aveugle après un échec au-delà de l'étape 5 (Secret officiel déjà modifié) : lire les logs avant de relancer. `concurrencyPolicy: Forbid` : jamais deux rotations en parallèle.

**Droits : `s3/s3-rotation-rbac.yaml`** — ServiceAccount `mlflow-s3-rotation` et un `Role` dans chaque namespace touché, limités aux objets de la rotation (`resourceNames`) quand l'API le permet. Dans `mlflow` : `get`/`patch` sur les trois PushSecrets, l'ExternalSecret `mlflow-s3-temp` et le Secret `mlflow-s3-credentials`, redémarrage du Deployment `mlflow`, `exec` pour la vérification finale. Dans `seaweedfs` : `get`/`patch` sur l'ExternalSecret `seaweedfs-s3-config`, `patch` des pods (annotation), `pods/exec` (sha256 du fichier monté, `kill -HUP 1`), `pods/log`. `pods/exec` sur SeaweedFS donne un accès complet à son conteneur : c'est le droit le plus sensible du job.

**Les ressources de rotation (`mlflow-s3-credentials-push`, `mlflow-s3-temp-access-push`, `mlflow-s3-temp-secret-push`, `mlflow-s3-temp`) sont déclenchées à la demande** (`refreshInterval: 0s` ou `refreshPolicy: OnChange`) : ils poussent à leur création, puis seulement quand l'objet PushSecret change (spec, labels ou annotations). Une modification du Secret source ne déclenche **rien** : ESO ne surveille pas les Secrets sources. Ils ne servent qu'à la rotation, qui les déclenche en changeant une annotation :

```bash
kubectl -n mlflow annotate pushsecret mlflow-s3-credentials-push force-sync=$(date +%s) --overwrite
kubectl -n mlflow annotate pushsecret mlflow-s3-temp-access-push mlflow-s3-temp-secret-push \
  force-sync=$(date +%s) --overwrite
kubectl -n mlflow annotate externalsecret mlflow-s3-temp force-sync=$(date +%s) --overwrite
```

Cette annotation n'étant pas dans Git, ArgoCD ne la voit pas comme une dérive.

Modifier le Secret `mlflow-s3-credentials` puis déclencher son PushSecret propage donc les clés à OpenBao, puis à SeaweedFS (rafraîchissement de l'`ExternalSecret` ≤ 1 h, mise à jour du fichier monté, **puis `SIGHUP`**, voir [SeaweedFS](#workloadsseaweedfss3-credentialsyaml)). Ne pas modifier `secret/seaweedfs/s3` directement dans OpenBao : le prochain déclenchement du PushSecret le réécrirait avec la valeur du Secret.

> ESO refuse d'écrire dans un secret OpenBao qu'il n'a pas créé (`secret not managed by external-secrets`) : il vérifie la métadonnée `managed-by=external-secrets`, qu'il pose lui-même quand il crée le chemin. Ne pas créer `secret/seaweedfs/s3` à la main, sinon tous les PushSecrets échouent. Si c'est déjà fait : `bao kv metadata put -custom-metadata=managed-by=external-secrets secret/seaweedfs/s3`. Cette métadonnée ne peut pas être posée depuis un PushSecret : le provider Vault ignore les labels du template et les `metadata` des entrées.

> Le chart crée un Secret `mlflow-flask-server-secret-key` aléatoire en hook `pre-install` (→ PreSync sous ArgoCD, recréé à chaque sync puisque `lookup` ne fonctionne pas). Sans authentification MLflow, cette clé n'a pas d'effet utile ; elle ne provoque pas d'OutOfSync.

### `apps/platform/reloader/application.yaml`

Application **`reloader`** (sync-wave `0`) — chart `reloader` **2.2.19** de Stakater (Reloader v1.4.23) dans `reloader`.

Reloader surveille les Secrets et ConfigMaps du cluster et fait un *rollout restart* des Deployments / StatefulSets / DaemonSets qui les utilisent quand leur contenu change. Il complète ESO : ESO met le Secret à jour, Reloader fait relire la nouvelle valeur aux applis qui ne la chargent qu'au démarrage (variables d'environnement).

- **Opt-in** (`autoReloadAll: false`, défaut du chart) : seuls les workloads annotés sont redémarrés. On nomme les Secrets surveillés plutôt que `reloader.stakater.com/auto: "true"`, pour ne pas redémarrer sur un Secret dont l'appli gère elle-même le changement :
  ```yaml
  secret.reloader.stakater.com/reload: "secret-a,secret-b"
  ```
- **`reloadStrategy: annotations`** : Reloader modifie une annotation du template de pod (comme `kubectl rollout restart`) au lieu d'ajouter une variable d'environnement aux conteneurs. ArgoCD ne gère pas ce champ : pas de dérive, et `selfHeal` n'annule pas le redémarrage.
- Pas de redémarrage si ESO réécrit un Secret sans en changer les valeurs (Reloader compare un hash du contenu).
- `readOnlyRootFileSystem: true`.

Workloads concernés :

| Workload | Secret surveillé | Pourquoi |
|---|---|---|
| `mlflow` (Deployment) | `mlflow-postgres-credentials` | Mot de passe Postgres changé par OpenBao toutes les 24 h, lu au démarrage |

Volontairement **non annotés** :

- `mlflow` / `mlflow-s3-credentials` : le [job de rotation S3](#appsplatformmlflowapplicationyaml) redémarre MLflow lui-même, à l'étape 7, **avant** de révoquer l'ancienne paire. Reloader le redémarrerait en plus, dès l'étape 5 ;
- SeaweedFS / `seaweedfs-s3-config` : rechargé sans coupure par `SIGHUP` ; un redémarrage couperait S3 (un seul pod) ;
- PostgreSQL / `postgres-admin` : le mot de passe n'est lu qu'à l'initialisation du volume, un redémarrage n'y changerait rien.

```bash
# Redémarrages effectués par Reloader
kubectl -n reloader logs deploy/reloader-reloader | grep -i reload
```

### `apps/platform/prometheus/application.yaml`

Application **`prometheus`** — chart OCI `kube-prometheus-stack` **92.3.1**, release `prometheus`, dans `monitoring`.

- **Exclue de `root`** : n'est **pas** déployée automatiquement (voir [Déployer Prometheus](#déployer--arrêter-prometheus)).
- Prometheus en NodePort **30060**, Grafana en NodePort **30070** (mot de passe admin `admin`).
- `prometheus-node-exporter.hostRootFsMount.enabled: false` : le montage de la racine de l'hôte ne fonctionne pas sous WSL2.
- `prune: true`, `selfHeal: false`, `CreateNamespace`, `ServerSideApply`.

### `workloads/eso-config/cluster-secret-store.yaml`

**`ClusterSecretStore` `openbao-backend`** (cluster-scoped, utilisable depuis n'importe quel namespace), référencé par tous les `ExternalSecret` du repo :
- provider `vault` (OpenBao est compatible avec l'API Vault) ;
- serveur `http://openbao.openbao.svc:8200` (DNS interne du cluster) ;
- moteur KV **v2** monté sur `secret` ;
- authentification par token, lu dans le Secret **`vault-token`** (clé `token`) du namespace `external-secrets` — **à créer à la main**, voir [Prérequis manuels](#prérequis-manuels-secrets).

### `workloads/eso-config/cluster-secret-store-database.yaml`

**`ClusterSecretStore` `openbao-database`** : même serveur et même token que `openbao-backend`, mais pointé sur le moteur **`database`** d'OpenBao (identifiants PostgreSQL générés et changés par OpenBao).
- `path: database`, `version: v1` : ESO fait une lecture brute de `database/<key>`. Avec `v2`, il insérerait `data/` dans le chemin (spécifique au KV v2) et la lecture échouerait.
- Exemple : `key: static-creds/mlflow-role` → `GET database/static-creds/mlflow-role` (`username`, `password`, `ttl`…).

### `roar-k8s-helm.yaml`

Reliquat d'un exercice du cours (Application `helm-demo` pointant vers le repo `roar-k8s-helm`, projet `helmproj`).

- **Non géré par le GitOps** : il est à la racine, hors de `apps/`, donc aucune Application racine ne le lit.
- Incomplet tel quel (pas de `apiVersion` ni de `kind`) : c'est un extrait, pas un manifest applicable.

---

## Installation depuis zéro

Seule la branche `bootstrap` est nécessaire :

```bash
# 0. Télécharger uniquement la branche bootstrap
git clone --branch bootstrap --single-branch \
  https://github.com/jeanbaptiste-billaud/ArgoCD_Udemy.git ArgoCD_Udemy-bootstrap
cd ArgoCD_Udemy-bootstrap

# 1. Kubernetes (désactiver d'abord l'intégration Docker Desktop dans WSL2)
./install_kub_microk8s.sh

# 2. ArgoCD + bootstrap GitOps
./install_ArgoCD.sh

# 3. Créer les secrets manuels (voir section suivante)

# 4. Vérifier
argocd app list
kubectl -n argocd get applications
```

Déroulé côté ArgoCD après le `kubectl apply -f root-app.yaml` :

1. `root` (projet `default`) synchronise `main:apps/`.
2. `root-projects` (wave `-1`) crée l'AppProject `infra`. Les autres Applications (projet `infra`) réessaient jusqu'à ce qu'il existe.
3. `argocd` reprend la release Helm installée par le script, avec les values complètes de `manifests/argocd/values.yaml`.
4. `external-secrets-operator` et `openbao` s'installent.
5. `eso-config` attend les CRDs ESO, puis crée le `ClusterSecretStore`.

---

## Prérequis manuels (secrets)

Ces éléments sont **volontairement hors de Git** (ce sont des secrets) et doivent être créés à la main.

### 1. Initialiser OpenBao (une seule fois)

```bash
kubectl -n openbao exec openbao-0 -- \
  bao operator init -key-shares=1 -key-threshold=1
```

La commande affiche une **Unseal Key** et un **Initial Root Token**. ⚠️ **Ils ne sont affichés qu'une fois** : les conserver hors de Git (gestionnaire de mots de passe). Sans la clé d'unseal, les données sont irrécupérables.

### 2. Déverrouiller OpenBao (après chaque redémarrage du pod)

```bash
kubectl -n openbao exec openbao-0 -- bao operator unseal <unseal-key>
```

### 3. Activer le moteur KV v2 (une seule fois)

Contrairement au mode dev, rien n'est monté par défaut :

```bash
kubectl -n openbao exec openbao-0 -- sh -c \
  'BAO_TOKEN=<root-token> bao secrets enable -path=secret kv-v2'
```

### 4. Token d'accès d'ESO à OpenBao

```bash
kubectl -n external-secrets create secret generic vault-token \
  --from-literal=token=<root-token>
```

### 5. Identifiants S3 de SeaweedFS

Seule l'identité `admin` (tous les droits) est créée à la main :

```bash
kubectl -n openbao exec openbao-0 -- sh -c \
  'BAO_TOKEN=<root-token> bao kv put secret/seaweedfs/admin accessKey=<access-key> secretKey=<secret-key>'
```

Les clés de l'identité `mlflow` (`secret/seaweedfs/s3`) sont **générées par ESO** à la synchronisation de l'Application `mlflow` (`mlflow-s3-bootstrap-access-push` / `mlflow-s3-bootstrap-secret-push`). Ne **pas** créer ce chemin à la main, sinon ESO refuse d'y écrire (voir [MLflow](#appsplatformmlflowapplicationyaml)). D'ici là, l'`ExternalSecret` de SeaweedFS (wave `2`) est en erreur et réessaie : c'est normal, `mlflow` est en wave `3`.

ESO crée alors le Secret `seaweedfs-s3-config` et le pod SeaweedFS démarre. Les clés `mlflow` sont aussi utilisées par MLflow : après l'amorçage, c'est le Secret Kubernetes `mlflow-s3-credentials` qui fait foi (voir [MLflow](#appsplatformmlflowapplicationyaml)). Après un changement de clés, recharger la config S3 de SeaweedFS par `SIGHUP`, sans redémarrage (voir [SeaweedFS](#workloadsseaweedfss3-credentialsyaml)).

### 6. Superutilisateur PostgreSQL

```bash
kubectl -n openbao exec openbao-0 -- sh -c \
  'BAO_TOKEN=<root-token> bao kv put secret/postgres/admin username=postgres password=<mot-de-passe>'
```

### 7. Moteur `database` d'OpenBao (identifiants de la base MLflow)

Le mot de passe du rôle PostgreSQL `mlflow` est géré par OpenBao. À faire **après** le premier sync de `postgres` (le Job `db-mlflow` doit avoir créé le rôle `mlflow`).

Rôle PostgreSQL utilisé par OpenBao, capable de changer le mot de passe des rôles applicatifs :

```bash
kubectl -n postgres exec postgres-0 -- psql -U admin -d postgres -c \
  "CREATE ROLE openbao LOGIN CREATEROLE PASSWORD '<mot-de-passe-openbao>'; GRANT mlflow TO openbao WITH ADMIN OPTION;"
```

Moteur, connexion et static role :

```bash
kubectl -n openbao exec openbao-0 -- sh -c 'export BAO_TOKEN=<root-token>
  bao secrets enable database
  bao write database/config/my-postgresql-database \
    plugin_name=postgresql-database-plugin \
    connection_url="postgresql://{{username}}:{{password}}@postgres.postgres.svc.cluster.local:5432/postgres?sslmode=disable" \
    username=openbao password=<mot-de-passe-openbao> \
    password_authentication=scram-sha-256 \
    allowed_roles="*-role"
  bao write database/static-roles/mlflow-role \
    db_name=my-postgresql-database username=mlflow rotation_period=24h'
```

À la création du static role, OpenBao change aussitôt le mot de passe de `mlflow` ; MLflow le lit via `static-creds/mlflow-role`.

Les données sont persistées sur le PVC : elles survivent aux redémarrages (il suffit de refaire l'unseal).

Vérification :

```bash
kubectl get clustersecretstore openbao-backend      # STATUS = Valid
kubectl -n seaweedfs get externalsecret,secret seaweedfs-s3-config   # SecretSynced
kubectl -n seaweedfs get pods                                        # seaweedfs-all-in-one-* Running
kubectl -n postgres get externalsecret,pods                          # SecretSynced, postgres-0 Running
kubectl -n postgres exec postgres-0 -- psql -U postgres -c '\l'    # la base mlflow existe
kubectl -n mlflow get externalsecret,pods                            # SecretSynced, mlflow-* Running
```

---

## Accès aux interfaces

Récupérer l'IP du nœud :

```bash
kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}'
```

| Interface | URL | Identifiants |
|---|---|---|
| ArgoCD | `http://<IP>:30080` | `admin` / `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' \| base64 -d` |
| OpenBao | `http://<IP>:30200` | root token obtenu au `bao operator init` |
| SeaweedFS S3 | `http://<IP>:30333` | identité `admin` : `secret/seaweedfs/admin` ; identité `mlflow` : `secret/seaweedfs/s3` |
| MLflow | `http://<IP>:30500` | — (pas d'authentification) |
| Prometheus | `http://<IP>:30060` | — (si déployé) |
| Grafana | `http://<IP>:30070` | `admin` / `admin` (si déployé) |

Connexion CLI :

```bash
argocd login <IP>:30080 --username admin --password <mdp> --insecure --grpc-web
```

---

## Ordre de déploiement (sync waves)

L'annotation `argocd.argoproj.io/sync-wave` ordonne la création des objets **au sein d'une même Application parente**. Les waves les plus basses sont appliquées en premier, et ArgoCD attend qu'elles soient saines avant de passer à la suivante.

| Wave | Objet | Parent | Pourquoi |
|---|---|---|---|
| `-1` | `root-projects` | `root` | L'AppProject `infra` doit exister avant les apps qui l'utilisent |
| `-1` | `argocd` | `root` | ArgoCD avant le reste |
| `0` | `external-secrets-operator`, `openbao`, `reloader` | `root` | Composants indépendants |
| `1` | `eso-config` | `root` | A besoin des CRDs installées par l'opérateur ESO |
| `2` | `seaweedfs`, `postgres` | `root` | Ont besoin du `ClusterSecretStore` créé par `eso-config` |
| `3` | `mlflow` | `root` | A besoin de PostgreSQL et de SeaweedFS (bucket `mlflow`) |

---

## Opérations courantes

### Ajouter un nouveau composant

1. Créer `apps/platform/<composant>/application.yaml` (s'inspirer d'`openbao`) avec `project: infra`.
2. Si le chart vient d'un **nouveau repo** ou cible un **nouveau namespace**, l'ajouter dans `projects/infra-project.yaml` (`sourceRepos` / `destinations`).
3. Commit + push sur `main`. `root` crée l'Application automatiquement — **aucune action sur la branche `bootstrap`**.

### Ajouter un nouvel AppProject

1. Créer `projects/<nom>-project.yaml` (un `kind: AppProject`, `namespace: argocd`).
2. Commit + push. `root-projects` le crée automatiquement.
3. Ne **pas** définir le même AppProject ailleurs.

### Ajouter des manifests bruts (non-Helm)

1. Les placer dans `workloads/<nom>/`.
2. Créer une Application dans `apps/` qui pointe dessus (`path: workloads/<nom>`), comme `eso-config`.

### Déployer / arrêter Prometheus

Prometheus est exclu de `root` (`exclude: 'platform/prometheus/*'` dans `root-app.yaml`, branche `bootstrap`).

```bash
# Déployer
kubectl apply -f apps/platform/prometheus/application.yaml

# Arrêter (supprime toute la stack grâce au finalizer ; les CRDs restent)
kubectl -n argocd delete application prometheus
kubectl delete namespace monitoring
```

Pour le refaire gérer automatiquement par ArgoCD, retirer la ligne `exclude` de `root-app.yaml` (branche `bootstrap`), pousser, puis **réappliquer** `kubectl apply -f root-app.yaml` (`root` n'est pas surveillée par ArgoCD).

### Mettre à jour ArgoCD

Changer `targetRevision` (chart) dans `apps/platform/argocd/application.yaml` sur `main`. Commit + push. Pour que les futures installations partent de la même version, mettre aussi à jour `--version` dans `install_ArgoCD.sh` sur la branche `bootstrap`.

### Ajouter une base PostgreSQL

Pour une nouvelle application `<appli>` :

1. Copier le dossier `workloads/postgres/databases/mlflow/` en `workloads/postgres/databases/<appli>/` et remplacer `mlflow` par `<appli>` (nom du Job, `DB_NAME`, `DB_USER`).
2. Commit + push : l'Application `postgres` se synchronise et le Job crée le rôle (sans mot de passe) et la base.
3. Créer le static role dans OpenBao (la connexion `my-postgresql-database` accepte tout rôle `*-role`) :
   ```bash
   kubectl -n openbao exec openbao-0 -- sh -c \
     'BAO_TOKEN=<root-token> bao write database/static-roles/<appli>-role db_name=my-postgresql-database username=<appli> rotation_period=24h'
   ```
4. Dans les manifests de l'appli, ajouter un `ExternalSecret` sur le store `openbao-database`, clé `static-creds/<appli>-role`, dans **son** namespace, et la faire pointer vers `postgres.postgres.svc:5432`, base `<appli>`.

Retirer le dossier ne supprime **pas** la base (le Job ne fait que créer) : supprimer le static role (`bao delete database/static-roles/<appli>-role`), puis faire un `DROP DATABASE` / `DROP ROLE` à la main si besoin.

Pour forcer un changement de mot de passe : `bao write -f database/rotate-role/<appli>-role`.

### Utiliser MLflow

Depuis l'hôte (ou un notebook) — seule l'URL du serveur est nécessaire, les artefacts passent par MLflow :

```python
import mlflow
mlflow.set_tracking_uri("http://<IP>:30500")    # dans le cluster : http://mlflow.mlflow.svc
mlflow.set_experiment("demo")
with mlflow.start_run():
    mlflow.log_param("alpha", 0.5)
    mlflow.log_metric("rmse", 0.42)
    mlflow.log_text("hello", "hello.txt")      # artefact -> s3://mlflow sur SeaweedFS
```

Vérifier que l'artefact est bien dans SeaweedFS :

```bash
AWS_ACCESS_KEY_ID=<access-key> AWS_SECRET_ACCESS_KEY=<secret-key> \
  aws --endpoint-url http://<IP>:30333 s3 ls --recursive s3://mlflow
```

### Forcer un rafraîchissement

```bash
argocd app get <app> --refresh          # relit Git
argocd app sync <app>                   # applique
argocd app diff <app>                   # montre l'écart Git ↔ cluster
```

---

## Choix techniques et pièges connus

### `caBundle` et `ignoreDifferences`

Les opérateurs exposant un **webhook d'admission** (ESO, l'agent injector d'OpenBao, cert-manager, Kyverno…) doivent être joignables en HTTPS par l'API server. Ils génèrent leur propre CA au démarrage et **injectent eux-mêmes** le certificat de cette CA dans le champ `clientConfig.caBundle` de leur `ValidatingWebhookConfiguration` / `MutatingWebhookConfiguration`.

Le chart Helm livre ce champ vide (il ne peut pas connaître la CA à l'avance). Sans configuration, ArgoCD voit donc un écart permanent, et avec `selfHeal` il vide le champ, l'opérateur le remet, etc. — l'app oscille entre Synced et OutOfSync et le webhook est cassé par intermittence.

Solution appliquée dans `external-secrets-operator` (et dans `openbao` tant que son agent injector était activé) :

```yaml
ignoreDifferences:
  - group: admissionregistration.k8s.io
    kind: ValidatingWebhookConfiguration   # ou MutatingWebhookConfiguration
    jqPathExpressions:
      - .webhooks[]?.clientConfig.caBundle
syncPolicy:
  syncOptions:
    - RespectIgnoreDifferences=true        # n'écrase pas le champ lors d'un sync
```

### Un objet = un seul propriétaire

Si deux Applications (ou une Application + un `helm install` manuel) gèrent le même objet, elles le réécrivent chacune leur tour. Deux cas rencontrés :

- **AppProject `infra` défini à la fois dans l'ancien `root-app.yaml` et dans `projects/`** → l'app `argocd` passait en OutOfSync en boucle. Il n'est désormais défini que dans `projects/`.
- **ESO installé deux fois** (un `helm install external-secrets` manuel + l'Application ArgoCD) → les deux cert-controllers réécrivaient les mêmes webhooks avec des services et des CA différents. L'install manuelle a été retirée.

Pour diagnostiquer : `argocd app diff <app>` et
`kubectl get <objet> --show-managed-fields -o yaml` (champ `managedFields` : qui a écrit quoi, et quand).

> Ne jamais faire `helm uninstall` d'une release dont les **CRDs** sont partagées avec une Application ArgoCD : la désinstallation supprimerait les CRDs, donc **toutes les ressources de ce type** dans le cluster.

### Finalizers et suppressions en cascade

- `resources-finalizer.argocd.argoproj.io` sur une Application : la supprimer supprime **toutes les ressources** qu'elle a créées.
- `root` a `prune: true` : retirer un fichier de `apps/` supprime l'Application, donc (finalizer) tout ce qu'elle déploie.
- Pour supprimer une Application **sans** toucher à ses ressources, retirer d'abord son finalizer :

  ```bash
  kubectl -n argocd patch app <app> --type json \
    -p '[{"op":"remove","path":"/metadata/finalizers"}]'
  kubectl -n argocd delete app <app>
  ```

- L'annotation `argocd.argoproj.io/sync-options: Delete=false` protège un objet contre ces suppressions (utilisée sur `root-projects` et l'AppProject `infra`).

### `ServiceMonitor` sans Prometheus

`manifests/argocd/values.yaml` active des `ServiceMonitor`, mais leur CRD n'existe que si kube-prometheus-stack est installé. D'où :
- des values **minimales sans `ServiceMonitor`** pour le `helm install` de la branche `bootstrap` (il échouerait sinon) ;
- `SkipDryRunOnMissingResource=true` dans l'Application `argocd`.

Les CRDs de Prometheus sont conservées lorsqu'on supprime la stack, ce qui garde les `ServiceMonitor` valides.

---

## Sécurité

Ce repo est un **lab local**. Plusieurs choix sont inacceptables en production :

| Point | Où | En production |
|---|---|---|
| OpenBao mono-instance, HTTP sans TLS, 1 seule clé d'unseal, unseal manuel | `manifests/openbao/values.yaml` | Mode HA (Raft), TLS, plusieurs clés (Shamir) ou auto-unseal |
| ESO s'authentifie avec le token root | `workloads/eso-config/cluster-secret-store*.yaml` + secret `vault-token` | Auth Kubernetes OpenBao + policy en lecture seule |
| Mot de passe Grafana `admin` en clair dans Git | `apps/platform/prometheus/application.yaml` | Secret externe (ESO) via `grafana.admin.existingSecret` |
| ArgoCD en HTTP (`server.insecure: true`) | `manifests/argocd/values.yaml` + `argocd-values.yaml` (branche `bootstrap`) | TLS via Ingress |
| Services en NodePort | plusieurs | Ingress + authentification |
| SeaweedFS mono-pod, S3 en HTTP, identité `admin` à tous les droits | `manifests/seaweedfs/values.yaml`, `workloads/seaweedfs/` | Composants séparés et répliqués, TLS, identité admin réservée à l'exploitation |
| MLflow sans authentification, `serverAllowedHosts: *` | `manifests/mlflow/values.yaml` | `auth`/OIDC activé, liste d'hôtes explicite, Ingress TLS |
| PostgreSQL mono-instance sans sauvegarde | `workloads/postgres/` | Opérateur (CloudNativePG) avec réplication et sauvegardes |
| `clusterResourceWhitelist: */*` | `projects/infra-project.yaml` | Liste restreinte des kinds nécessaires |

---

## Sources

- MicroK8s sous WSL2 : <https://canonical.com/microk8s/docs/install-wsl2>
- Premier pod sur Kubernetes : <https://medium.com/@oshokry1/install-kubernetes-on-your-machine-and-run-a-hello-world-pod-6aa378a51e81>
- Installation d'ArgoCD : <https://blog.stephane-robert.info/docs/pipeline-cicd/argocd/installation/>
- ArgoCD — App of apps : <https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/>
- ArgoCD — Diffing / ignoreDifferences : <https://argo-cd.readthedocs.io/en/stable/user-guide/diffing/>
- ArgoCD — Sync waves : <https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/>
- External Secrets Operator : <https://external-secrets.io/>
- OpenBao : <https://openbao.org/>
- SeaweedFS (chart Helm) : <https://github.com/seaweedfs/seaweedfs/tree/master/k8s/charts/seaweedfs>
- MLflow (chart community-charts) : <https://community-charts.github.io/docs/charts/mlflow/usage>
- MLflow — stockage d'artefacts S3 : <https://mlflow.org/docs/latest/self-hosting/architecture/artifact-store/>
