"""
Pin `backend/api/schema.sql` byte-identical to `docs/architecture/database_schema.sql`.

The doc is the design record (CLAUDE.md Reference docs list); the
backend ships its own copy so Docker images don't need the docs/
directory at runtime. To stop them drifting silently, this test
asserts they're identical — drift this and CI fails.
"""
from pathlib import Path


def test_backend_schema_matches_design_doc():
    backend_schema = Path(__file__).parent.parent / "api" / "schema.sql"
    design_doc = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "architecture"
        / "database_schema.sql"
    )
    assert backend_schema.exists(), backend_schema
    assert design_doc.exists(), design_doc
    assert backend_schema.read_bytes() == design_doc.read_bytes(), (
        f"backend/api/schema.sql has drifted from docs/architecture/database_schema.sql.\n"
        f"  Run: cp {design_doc} {backend_schema}"
    )
