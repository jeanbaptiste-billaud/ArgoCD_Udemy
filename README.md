# ArgoCD_Udemy

Lab GitOps d'un cluster Kubernetes local (MicroK8s sous WSL2), entièrement piloté par **ArgoCD** selon le pattern **app-of-apps**.

Le repo a **deux branches** :

| Branche | Contenu | Usage |
|---|---|---|
| **`bootstrap`** | Scripts d'installation (MicroK8s, ArgoCD) + `root-app.yaml` | Téléchargée une seule fois pour installer le cluster |
| **`main`** | Toutes les Applications et leur configuration | Seule source de vérité ensuite |

Une fois le bootstrap effectué, **Git est la seule source de vérité** : toute modification du cluster passe par un commit sur `main`, qu'ArgoCD applique automatiquement. `main` ne dépend jamais de la branche `bootstrap`.

Composants déployés :

| Composant | Rôle | Namespace |
|---|---|---|
| **ArgoCD** | Moteur GitOps, se gère lui-même depuis ce repo | `argocd` |
| **External Secrets Operator (ESO)** | Synchronise des secrets externes vers des `Secret` Kubernetes | `external-secrets` |
| **OpenBao** | Coffre-fort de secrets (fork open source de Vault), en mode standalone (stockage persistant) | `openbao` |
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
    ROOT -. exclu .-> PROM[Application<br/>prometheus]

    ARGO -->|chart argo-cd + values| ARGOCD[(ArgoCD)]
    ESO -->|chart external-secrets| ESOD[(ESO)]
    ESOC -->|workloads/eso-config| CSS[(ClusterSecretStore<br/>+ ExternalSecret)]
    BAO -->|chart openbao| BAOD[(OpenBao)]
    PROM -.->|chart kube-prometheus-stack| PROMD[(Monitoring)]

    CSS -->|lit les secrets| BAOD
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
│       └── prometheus/
│           └── application.yaml       # kube-prometheus-stack — EXCLU de root
├── manifests/                         # values Helm référencées par des Applications ($values)
│   ├── argocd/
│   │   └── values.yaml                # values complètes d'ArgoCD
│   └── openbao/
│       └── values.yaml
├── workloads/                         # manifests "bruts" référencés par des Applications
│   └── eso-config/
│       └── eso.yaml                   # ClusterSecretStore OpenBao + ExternalSecret de démo
└── roar-k8s-helm.yaml                 # exercice du cours, NON géré par le GitOps
```

### Logique de découpage

| Dossier | Contient | Synchronisé par | Règle |
|---|---|---|---|
| branche `bootstrap` | Scripts d'installation + point d'entrée | appliqué à la main, une fois | Ne contient que ce qui est nécessaire *avant* qu'ArgoCD tourne |
| `projects/` | Uniquement des `AppProject` | `root-projects` | Un fichier par projet |
| `apps/` | Uniquement des `Application` ArgoCD | `root` (récursif) | Un dossier par composant, un fichier `application.yaml`. **Aucun autre YAML** (sinon `root` essaie de l'appliquer) |
| `manifests/` | Fichiers de values Helm | lus via `$values` par une Application | Jamais synchronisé directement |
| `workloads/` | Manifests Kubernetes classiques | une Application de `apps/` qui pointe dessus | Jamais synchronisé directement par une app racine |

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
  - `ghcr.io/prometheus-community/charts` (chart OCI kube-prometheus-stack).
- **`destinations`** — où elles peuvent déployer : `argocd`, `external-secrets`, `openbao`, `monitoring`, `production`, `kube-system` (certains charts y posent des composants, ex. Services de kubelet pour Prometheus).
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

Application **`eso-config`** (sync-wave `1`, donc **après** l'opérateur) — déploie `workloads/eso-config/` dans le namespace `production`.

- Séparée de l'opérateur car elle crée des objets (`ClusterSecretStore`, `ExternalSecret`) dont les **CRDs sont installées par l'opérateur**.
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

### `apps/platform/prometheus/application.yaml`

Application **`prometheus`** — chart OCI `kube-prometheus-stack` **92.3.1**, release `prometheus`, dans `monitoring`.

- **Exclue de `root`** : n'est **pas** déployée automatiquement (voir [Déployer Prometheus](#déployer--arrêter-prometheus)).
- Prometheus en NodePort **30060**, Grafana en NodePort **30070** (mot de passe admin `admin`).
- `prometheus-node-exporter.hostRootFsMount.enabled: false` : le montage de la racine de l'hôte ne fonctionne pas sous WSL2.
- `prune: true`, `selfHeal: false`, `CreateNamespace`, `ServerSideApply`.

### `workloads/eso-config/eso.yaml`

Configuration ESO de démonstration :

- **`ClusterSecretStore` `openbao-backend`** (cluster-scoped, utilisable depuis n'importe quel namespace) :
  - provider `vault` (OpenBao est compatible avec l'API Vault) ;
  - serveur `http://openbao.openbao.svc:8200` (DNS interne du cluster) ;
  - moteur KV **v2** monté sur `secret` ;
  - authentification par token, lu dans le Secret **`vault-token`** (clé `token`) du namespace `external-secrets` — **à créer à la main**, voir [Prérequis manuels](#prérequis-manuels-secrets).
- **`ExternalSecret` `db-credentials`** (namespace `production`) :
  - lit la propriété `password` du secret OpenBao `production/db` (chemin complet `secret/data/production/db`) ;
  - crée et maintient le Secret Kubernetes `db-credentials` (clé `password`), rafraîchi toutes les minutes ;
  - `creationPolicy: Owner` : le Secret généré est supprimé si l'`ExternalSecret` l'est.

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
5. `eso-config` attend les CRDs ESO, puis crée le `ClusterSecretStore` et l'`ExternalSecret`.

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

### 5. Secret de démo dans OpenBao

```bash
kubectl -n openbao exec openbao-0 -- sh -c \
  'BAO_TOKEN=<root-token> bao kv put secret/production/db password=<mot-de-passe>'
```

Les données sont persistées sur le PVC : elles survivent aux redémarrages (il suffit de refaire l'unseal).

Vérification :

```bash
kubectl get clustersecretstore openbao-backend      # STATUS = Valid
kubectl -n production get externalsecret            # STATUS = SecretSynced
kubectl -n production get secret db-credentials -o jsonpath='{.data.password}' | base64 -d
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
| `0` | `external-secrets-operator`, `openbao` | `root` | Composants indépendants |
| `1` | `eso-config` | `root` | A besoin des CRDs installées par l'opérateur ESO |

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
| ESO s'authentifie avec le token root | `workloads/eso-config/eso.yaml` + secret `vault-token` | Auth Kubernetes OpenBao + policy en lecture seule |
| Mot de passe Grafana `admin` en clair dans Git | `apps/platform/prometheus/application.yaml` | Secret externe (ESO) via `grafana.admin.existingSecret` |
| ArgoCD en HTTP (`server.insecure: true`) | `manifests/argocd/values.yaml` + `argocd-values.yaml` (branche `bootstrap`) | TLS via Ingress |
| Services en NodePort | plusieurs | Ingress + authentification |
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
