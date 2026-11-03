"""Verifications HTTP."""
import urllib.error
import urllib.request


def status(url: str, headers: dict[str, str] | None = None, timeout: float = 10) -> str:
    """Code HTTP de la reponse, "000" si la connexion echoue (comme curl -w '%{http_code}')."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as r:
            return str(r.status)
    except urllib.error.HTTPError as e:  # 403, 404... : urllib leve une exception
        return str(e.code)
    except urllib.error.URLError:
        return "000"
