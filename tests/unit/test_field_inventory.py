"""Unit tests for field_inventory (mapping discovery query wiring)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.field_inventory import list_field_inventory


@pytest.mark.asyncio
async def test_list_field_inventory_returns_triples():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [
        ("child-new-patient-history", "v1", "sfid_aaaaaaaa"),
        ("tbi-intake", "v1", "sfid_bbbbbbbb"),
    ]
    db.execute = AsyncMock(return_value=mock_result)

    rows = await list_field_inventory(db)

    assert rows == [
        ("child-new-patient-history", "v1", "sfid_aaaaaaaa"),
        ("tbi-intake", "v1", "sfid_bbbbbbbb"),
    ]
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_list_field_inventory_filters_passed_to_query():
    """Ensure optional filters are accepted (execute is invoked)."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    await list_field_inventory(
        db,
        intake_type_id="tbi-intake",
        intake_type_version="v1",
        unmapped_only=True,
    )

    db.execute.assert_called_once()
