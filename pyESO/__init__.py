"""pyESO : briques generiques pour piloter des secrets geres par External Secrets Operator.

Modules :
  report -- logs, empreintes, verifications (PyESOError)
  kube   -- API Kubernetes : Secrets, Pods (exec, logs), Deployments (rollout)
  eso    -- declencher une synchro ExternalSecret / PushSecret et l'attendre
  probe  -- verifications HTTP (code de reponse)

Ce qui est propre a un usage (ex. rotation des cles S3) vit hors du package : s3_rotation/.
"""
