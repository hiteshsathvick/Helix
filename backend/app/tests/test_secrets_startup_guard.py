import pytest

from app.core.config import Settings
from app.core.secrets_guard import check_no_insecure_defaults


def test_allows_local_environment_with_default_secrets() -> None:
    settings = Settings(environment="local")
    check_no_insecure_defaults(settings)  # must not raise


def test_refuses_non_local_environment_with_default_jwt_key() -> None:
    settings = Settings(environment="staging")
    with pytest.raises(RuntimeError, match="JWT_SIGNING_KEYS"):
        check_no_insecure_defaults(settings)


def test_refuses_non_local_environment_with_default_connector_key() -> None:
    settings = Settings(
        environment="staging",
        jwt_signing_keys={"prod-key-1": "a-real-per-environment-secret"},
    )
    with pytest.raises(RuntimeError, match="CONNECTOR_ENCRYPTION_KEY"):
        check_no_insecure_defaults(settings)


def test_allows_non_local_environment_once_secrets_are_overridden() -> None:
    settings = Settings(
        environment="staging",
        jwt_signing_keys={"prod-key-1": "a-real-per-environment-secret"},
        connector_encryption_key="a-real-generated-fernet-key",
    )
    check_no_insecure_defaults(settings)  # must not raise
