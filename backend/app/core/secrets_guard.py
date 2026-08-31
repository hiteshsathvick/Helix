"""Startup guard against shipping local-dev secret defaults into a real
environment (SPEC.md §29, CLAUDE.md §5). `jwt_signing_keys` and
`connector_encryption_key` both carry committed defaults so local dev works
out of the box with no setup -- every other config value in this file warns
about that in a comment, but nothing previously *enforced* it. This checks
the running settings against the class's own declared defaults (a single
source of truth, so a future default change can't silently drift out of
sync with this check) and refuses to boot outside `environment == "local"`
if either is still unset.
"""

from app.core.config import Settings


def check_no_insecure_defaults(settings: Settings) -> None:
    if settings.environment == "local":
        return

    defaults = Settings.model_fields
    insecure: list[str] = []
    if settings.jwt_signing_keys == defaults["jwt_signing_keys"].default:
        insecure.append("JWT_SIGNING_KEYS")
    if settings.connector_encryption_key == defaults["connector_encryption_key"].default:
        insecure.append("CONNECTOR_ENCRYPTION_KEY")

    if insecure:
        names = ", ".join(insecure)
        raise RuntimeError(
            f"refusing to start in environment={settings.environment!r}: "
            f"{names} still use their local-dev default value(s). "
            "Set real secrets for this environment before starting the app."
        )
