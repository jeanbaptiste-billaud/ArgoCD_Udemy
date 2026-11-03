# Rotation des clés S3

Ce qui est propre à la rotation des clés S3, construit sur le package générique `pyESO` :

- `rotation.py` — `S3KeyRotation` : déroulé en 8 étapes, `main()` (option `--check` en lecture seule) ;
- `s3.py` — `s3_status` : appel S3 signé (SigV4), indépendant du backend (`botocore`) ;
- `seaweedfs.py` — `SeaweedFS` : backend S3, rechargement de la config par `SIGHUP` ;
- `rotate_<appli>.py` — un script par application : noms de ses ressources et vérifications propres.

Les scripts s'exécutent depuis la racine du repo (le dossier du script est ajouté au `sys.path`, d'où les imports `rotation` / `seaweedfs` / `s3`) :

```bash
uv run s3_rotation/rotate_mlflow.py --check
```
