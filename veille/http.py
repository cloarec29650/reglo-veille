"""Client HTTP poli : robots.txt respecté, délai entre requêtes, user-agent identifié."""

import time
import urllib.robotparser
from urllib.parse import urlsplit

import requests


class RobotsDisallowed(Exception):
    """Le robots.txt du site interdit l'URL demandée."""


def describe_error(e: Exception) -> str:
    """Message lisible pour le rapport. Un 401/403 signifie que le site refuse les robots :
    on ne contourne pas (pas d'usurpation de navigateur), la source passe en suivi manuel."""
    if isinstance(e, RobotsDisallowed):
        return "interdit par robots.txt : suivi manuel"
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status in (401, 403):
        return f"accès refusé aux robots ({status}) : suivi manuel"
    return f"{type(e).__name__}: {e}"[:200]


class PoliteSession:
    def __init__(self, user_agent: str, timeout_s: float = 20, min_delay_s: float = 1.5):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.min_delay_s = min_delay_s
        self._last_call: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                resp = self._throttled_get(f"{origin}/robots.txt")
                # robots.txt absent (4xx) = tout est autorisé ; erreur serveur = prudence, rien n'est autorisé.
                if resp.status_code >= 500:
                    parser.disallow_all = True
                else:
                    parser.parse(resp.text.splitlines() if resp.ok else [])
            except requests.RequestException:
                parser.disallow_all = True
            self._robots[origin] = parser
        return self._robots[origin]

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(self.user_agent, url)

    def _throttled_get(self, url: str, **kwargs) -> requests.Response:
        domain = urlsplit(url).netloc
        wait = self.min_delay_s - (time.monotonic() - self._last_call.get(domain, 0.0))
        if wait > 0:
            time.sleep(wait)
        try:
            return self.session.get(url, timeout=self.timeout_s, **kwargs)
        finally:
            self._last_call[domain] = time.monotonic()

    def get(self, url: str, *, check_robots: bool = True, **kwargs) -> requests.Response:
        """GET avec contrôle robots.txt (désactivable pour les API ouvertes documentées)."""
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(url)
        resp = self._throttled_get(url, **kwargs)
        resp.raise_for_status()
        return resp
