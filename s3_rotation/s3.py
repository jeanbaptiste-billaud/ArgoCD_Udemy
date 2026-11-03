"""Appels S3 signes (SigV4), independants du backend."""
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from pyESO.probe import status


def s3_status(endpoint: str, bucket: str, access: str, secret: str, region: str = "us-east-1") -> str:
    """Liste au plus un objet du bucket avec une requete signee SigV4.

    La secret key ne transite jamais : elle sert a calculer la signature (HMAC) de la
    requete, seule la signature part. 200 = paire acceptee, 403 = refusee.
    """
    url = f"{endpoint}/{bucket}?list-type=2&max-keys=1"
    req = AWSRequest(method="GET", url=url)
    S3SigV4Auth(Credentials(access, secret), "s3", region).add_auth(req)
    return status(url, headers=dict(req.headers))
