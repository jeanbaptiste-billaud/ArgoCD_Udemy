#!/bin/bash
set -euo pipefail

# Les chemins sont relatifs au dossier du script
cd "$(dirname "$0")"

# ------ Ajout du repo helm ------

helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# ------ Installation de Argo dans son namespace à partir de helm ------
helm install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --version 10.1.3 \
  -f argocd-values.yaml
# Values minimales : l'Application "argocd" (infra:apps/platform/argocd)
# reprend ensuite la release avec les values completes.

kubectl -n argocd rollout status deploy/argocd-server --timeout=300s

# ------ Installation CLI ------
curl -sSL -o argocd \
  https://github.com/argoproj/argo-cd/releases/download/v3.4.5/argocd-linux-amd64
chmod +x argocd
sudo mv argocd /usr/local/bin/

# ------ Récupérer le mot de passe initial ------
password=$(kubectl get secret argocd-initial-admin-secret \
  -n argocd \
  -o jsonpath="{.data.password}" | base64 -d)
echo "$password"

# ------ Recuperation IP du noeud Kub ------
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
echo "$NODE_IP"

# ------ Connexion à la CLI ------
argocd login $NODE_IP:30080 \
  --username admin \
  --password $password \
  --insecure \
  --grpc-web

# ------ Bootstrap GitOps : Application racine "root" -> infra:apps/ ------
kubectl apply -f root-app.yaml

# ------ Vérification finale ------
argocd app list
argocd version --short

# Sources:
#https://blog.stephane-robert.info/docs/pipeline-cicd/argocd/installation/
