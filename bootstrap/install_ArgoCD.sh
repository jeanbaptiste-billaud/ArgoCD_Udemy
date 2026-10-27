#!/bin/bash
set -euo pipefail

# ------ Ajout du repo helm ------

helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# ------ Installation de Argo dans son namespace à partir de helm ------
helm install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --version 10.1.3 \
  -f bootstrap/argocd-values.yaml \
  --set server.metrics.serviceMonitor.enabled=false \
  --set controller.metrics.serviceMonitor.enabled=false \
  --set repoServer.metrics.serviceMonitor.enabled=false
# ServiceMonitors desactives ici : la CRD n'existe pas tant que Prometheus
# n'est pas installe. L'Application "argocd" les reactive ensuite depuis Git.

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

# ------ Bootstrap GitOps : AppProject infra + root-apps ------
kubectl apply -f bootstrap/root-app.yaml

# ------ Vérification finale ------
argocd app list
argocd version --short

# Sources:
#https://blog.stephane-robert.info/docs/pipeline-cicd/argocd/installation/
