"""Production-boot guardrails: default/dev credentials must refuse to start.

Regression: the old per-field validators read info.data["environment"] before
that field was validated (declared later in the class), so they never fired.
"""

import pytest
from pydantic import ValidationError

from ai_core.config import Settings

# Keep the real .env and OS env out of these tests
_ISOLATED = {"_env_file": None}

PROD_OK = dict(
    environment="production",
    master_secret="s3cret-master",
    auth_secret="s3cret-auth",
    service_token="s3cret-service",
    minio_access_key="prod-access",
    minio_secret_key="prod-secret",
    database_url="postgresql://app:strongpass@db:5432/soulforge",
    dashscope_api_key="sk-x",
    **_ISOLATED,
)


def test_production_with_proper_secrets_boots():
    s = Settings(**PROD_OK)
    assert s.environment == "production"


def test_development_allows_defaults(monkeypatch):
    # Other tests may export secrets into os.environ; scrub so we exercise
    # the true defaults path.
    for var in ("MASTER_SECRET", "AUTH_SECRET", "SERVICE_TOKEN", "ENVIRONMENT"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(environment="development", **_ISOLATED)
    assert s.master_secret == "change-me-in-production"


@pytest.mark.parametrize(
    "override,needle",
    [
        ({"master_secret": "change-me-in-production"}, "MASTER_SECRET"),
        ({"auth_secret": ""}, "AUTH_SECRET"),
        ({"service_token": ""}, "SERVICE_TOKEN"),
        ({"minio_access_key": "minioadmin"}, "MINIO"),
        ({"minio_secret_key": "minioadmin"}, "MINIO"),
        (
            {"database_url": "postgresql://soulforge:soulforge_dev@localhost:5432/soulforge"},
            "DATABASE_URL",
        ),
    ],
)
def test_production_rejects_default_credentials(override, needle):
    cfg = {**PROD_OK, **override}
    with pytest.raises(ValidationError, match=needle):
        Settings(**cfg)
