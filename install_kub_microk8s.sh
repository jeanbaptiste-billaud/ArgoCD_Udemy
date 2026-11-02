#!/bin/bash
set -euo pipefail

## Désactiver au préalable l'intégration de docker desktop dans WSL2 !

# ------ microk8s install ------
sudo snap install microk8s --classic

# ------ Wait for MicroK8s to start ------
sudo microk8s status --wait-ready

# ------ Enable services and start using Kubernetes ------
sudo microk8s enable dns
sudo microk8s enable storage
sudo microk8s enable dashboard

# ------ Create aliases ------
echo "alias kubectl='microk8s kubectl'" >> ~/.bashrc
echo "alias helm='microk8s helm'" >> ~/.bashrc

# shellcheck disable=SC1090
source ~/.bashrc

# ------ Run your first pod ! ------
kubectl run test --restart=Never --image=hello-world -it

# ------ The test pod should be listed ------
kubectl get pod

# ------ More info about the pod ------
kubectl describe pod test

# ------ Delete the pod ------
kubectl delete pod test


#Sources:
#https://canonical.com/microk8s/docs/install-wsl2
#https://medium.com/@oshokry1/install-kubernetes-on-your-machine-and-run-a-hello-world-pod-6aa378a51e81
