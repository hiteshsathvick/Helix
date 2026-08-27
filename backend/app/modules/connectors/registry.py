"""Connector registry, keyed by Source.type -- mirrors agents/tools.py's
TOOLS dict pattern (a name -> implementation lookup other code goes
through rather than importing a connector class directly)."""

from app.modules.connectors.base import Connector
from app.modules.connectors.github import GitHubConnector
from app.modules.connectors.web import WebConnector

CONNECTORS: dict[str, Connector] = {
    "web": WebConnector(),
    "github": GitHubConnector(),
}
