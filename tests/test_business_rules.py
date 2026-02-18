import pytest

from app.domain.models import IdentityStatus, JobStatus
from app.services.credit_service import InsufficientCreditsError


class Workspace:
    def __init__(self, credits_balance):
        self.credits_balance = credits_balance


class FakeSession:
    def __init__(self, workspace):
        self.workspace = workspace

    async def get(self, model, workspace_id, with_for_update=False):
        return self.workspace

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_credits_spend_success():
    from app.services.credit_service import CreditService

    ws = Workspace(credits_balance=3)
    service = CreditService(FakeSession(ws))
    await service.spend_credits("ws", 1)
    assert ws.credits_balance == 2


@pytest.mark.asyncio
async def test_credits_spend_insufficient():
    from app.services.credit_service import CreditService

    ws = Workspace(credits_balance=0)
    service = CreditService(FakeSession(ws))
    with pytest.raises(InsufficientCreditsError):
        await service.spend_credits("ws", 1)


def test_status_enums_expected():
    assert IdentityStatus.READY.value == "READY"
    assert JobStatus.QUEUED.value == "QUEUED"


def test_templates_seed_file_exists_and_has_entries():
    import json
    from pathlib import Path

    data = json.loads(Path("app/domain/seed_templates.json").read_text(encoding="utf-8"))
    assert len(data) >= 2
    assert all("code" in item for item in data)
