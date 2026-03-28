"""Model/index alignment with Alembic migration `ix_canonical_values_canonical_id`."""

from app.models.canonical_value import CanonicalValue


def test_canonical_values_table_has_canonical_id_index():
    names = {ix.name for ix in CanonicalValue.__table__.indexes}
    assert "ix_canonical_values_canonical_id" in names
