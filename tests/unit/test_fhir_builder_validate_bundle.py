"""Tests for FHIR bundle validation in fhir_builder_worker._validate_bundle."""

import pytest

pytest.importorskip("fhir.resources")

from app.workers.fhir_builder_worker import _validate_bundle  # noqa: E402 — after importorskip


def test_validate_bundle_ok_minimal_collection():
    """Valid minimal Bundle passes."""
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
    assert _validate_bundle(bundle) == []


def test_validate_bundle_validation_error_returns_string():
    """Schema violations become a non-empty error list (no raise)."""
    bad = {"resourceType": "Patient", "id": "x"}  # not a Bundle — fhir.resources rejects
    errs = _validate_bundle(bad)
    assert len(errs) >= 1


def test_validate_bundle_non_validation_error_becomes_error_list(monkeypatch):
    """If model_validate raises something other than ValidationError, worker-style path still gets a list."""
    from app.workers import fhir_builder_worker as fb

    def boom(_d):
        raise TypeError("simulated internal error")

    monkeypatch.setattr(fb.Bundle, "model_validate", staticmethod(boom))
    errs = _validate_bundle({"resourceType": "Bundle"})
    assert len(errs) == 1
    assert "simulated internal error" in errs[0]
