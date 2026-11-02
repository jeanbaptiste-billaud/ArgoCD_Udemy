# ArgoCD_Udemy — branche `bootstrap`

Cette branche contient **uniquement ce qu'il faut pour démarrer le cluster** : installer Kubernetes, installer ArgoCD, puis lui donner le point d'entrée GitOps.

Toutes les applications et leur configuration vivent sur la branche **`main`**. Une fois le bootstrap fait, toute modification du cluster passe par un commit sur `main`, et cette branche ne sert plus.

## Contenu

| Fichier | Rôle |
|---|---|
| `install_kub_microk8s.sh` | 1. Installe MicroK8s sous WSL2 (addons `dns`, `storage`, `dashboard`, alias `kubectl`/`helm`) |
| `install_ArgoCD.sh` | 2. Installe ArgoCD (chart `argo-cd` **10.1.3**, release `argocd`) + CLI `argocd` **v3.4.5**, puis applique `root-app.yaml` |
| `argocd-values.yaml` | Values Helm **minimales** du premier install (NodePort `30080`, HTTP) |
| `root-app.yaml` | Application racine **`root`** : synchronise `main:apps/` (app-of-apps) |

## Installation

```bash
# Télécharger uniquement cette branche
git clone --branch bootstrap --single-branch \
  https://github.com/jeanbaptiste-billaud/ArgoCD_Udemy.git ArgoCD_Udemy-bootstrap
cd ArgoCD_Udemy-bootstrap

# 1. Kubernetes (désactiver d'abord l'intégration Docker Desktop dans WSL2)
./install_kub_microk8s.sh

# 2. ArgoCD + point d'entrée GitOps
./install_ArgoCD.sh

# 3. Vérifier
kubectl -n argocd get applications
```

Déroulé côté ArgoCD après le `kubectl apply -f root-app.yaml` :

1. `root` (projet `default`) synchronise `main:apps/`.
2. `root-projects` (wave `-1`) crée l'AppProject `infra`.
3. Les autres Applications (projet `infra`) réessaient jusqu'à ce qu'`infra` existe.
4. `argocd` reprend la release Helm installée par le script, avec les values complètes de `main:manifests/argocd/values.yaml`.
5. Les composants plateforme (ESO, OpenBao…) s'installent.

## Après l'installation : OpenBao et secrets manuels

Ces étapes sont volontairement hors de Git :

```bash
# 1. Initialiser OpenBao (une seule fois). CONSERVER l'Unseal Key et le Root Token affichés !
kubectl -n openbao exec openbao-0 -- bao operator init -key-shares=1 -key-threshold=1

# 2. Déverrouiller (à refaire après chaque redémarrage du pod)
kubectl -n openbao exec openbao-0 -- bao operator unseal <unseal-key>

# 3. Activer le moteur KV v2 sur secret/ (une seule fois)
kubectl -n openbao exec openbao-0 -- sh -c \
  'BAO_TOKEN=<root-token> bao secrets enable -path=secret kv-v2'

# 4. Token d'accès d'ESO à OpenBao
kubectl -n external-secrets create secret generic vault-token \
  --from-literal=token=<root-token>

# 5. Secret de démo
kubectl -n openbao exec openbao-0 -- sh -c \
  'BAO_TOKEN=<root-token> bao kv put secret/production/db password=<mot-de-passe>'
```

Le README de la branche `main` décrit le reste en détail (accès aux interfaces, opérations courantes, pièges connus).

## Modifier `root`

`root-app.yaml` **n'est pas surveillé par ArgoCD**. Ajouter une application ne demande **aucune** action ici : il suffit de la créer dans `main:apps/`.

On ne modifie ce fichier que pour changer `root` lui-même (dossier, branche, `exclude`…), puis on le réapplique :

```bash
kubectl apply -f root-app.yaml
```

> La version du chart (`10.1.3`) et le nom de release (`argocd`) doivent rester identiques à ceux de `main:apps/platform/argocd/application.yaml`. Sinon ArgoCD installerait une seconde copie de lui-même au lieu de reprendre la release existante.
