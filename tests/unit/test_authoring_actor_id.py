import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.authoring_mappings import MappingNotFound
from app.services.authoring_templates import TemplateNotFound


def test_deactivate_mapping_passes_x_actor_id_header():
    mid = uuid.uuid4()

    async def fake_deactivate(db, mapping_id, actor_id="api"):
        assert mapping_id == mid
        assert actor_id == "operator-1"
        raise MappingNotFound("not found")

    with patch(
        "app.api.v1.authoring.deactivate_mapping",
        new=fake_deactivate,
    ):
        client = TestClient(app)
        r = client.delete(
            f"/api/v1/authoring/mappings/{mid}",
            headers={"X-Actor-Id": "operator-1"},
        )
    assert r.status_code == 404


def test_deactivate_mapping_defaults_actor_when_header_missing():
    mid = uuid.uuid4()

    async def fake_deactivate(db, mapping_id, actor_id="api"):
        assert actor_id == "api"
        raise MappingNotFound("not found")

    with patch(
        "app.api.v1.authoring.deactivate_mapping",
        new=fake_deactivate,
    ):
        client = TestClient(app)
        r = client.delete(f"/api/v1/authoring/mappings/{mid}")
    assert r.status_code == 404


def test_deprecate_template_passes_x_actor_id_header():
    tid = uuid.uuid4()

    async def fake_deprecate(db, template_id, actor_id="api"):
        assert template_id == tid
        assert actor_id == "audit-bot"
        raise TemplateNotFound("not found")

    with patch(
        "app.api.v1.authoring.deprecate_template",
        new=fake_deprecate,
    ):
        client = TestClient(app)
        r = client.post(
            f"/api/v1/authoring/templates/{tid}/deprecate",
            headers={"X-Actor-Id": "audit-bot"},
        )
    assert r.status_code == 404
