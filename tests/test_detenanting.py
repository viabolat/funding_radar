"""The guard that keeps the de-tenanting audit from decaying.

Every other test here checks behaviour. This one checks the source itself, and
it exists because the audit it protects is a one-time sweep: without it, the
next person to write a helpful comment naming the seed tenant undoes the work
silently and nothing fails.

**A deviation from the plan, stated rather than quietly applied.** The plan's
verification 7b greps every `.py`/`.ts`/`.tsx`/`.yml`/`.md` file and excludes
the whole of `supabase/migrations/`. Run as written it both over- and
under-exempts: it would pass `0001`–`0003` and every future migration
unexamined, while failing on this repo's own test suite, where `test_match.py`
and `test_warehouse.py` assert the tenant name is *absent* — which they cannot
do without containing it.

So the scan excludes no directory. Four individual files are exempt, and three
of the four are held to an assertion below:

  * `supabase/migrations/0004_seed_vertical_freedom.sql` — the row the identity
    belongs in. `test_the_exempt_migration_is_the_one_that_holds_the_identity`
    pins that it still holds it. The other four migrations are scanned like any
    other source file; `0005`'s comments were rewritten to say "the seed
    organisation" rather than name it.
  * `tests/test_match.py`, `tests/test_warehouse.py` — they name the tenant only
    to assert its absence, or to name the seed migration file they parse.
    `test_the_exempt_tests_name_the_tenant_only_to_assert_its_absence` checks
    every such line mechanically, and fails if either file stops needing the
    exemption at all.
  * `tests/test_detenanting.py` — this file, self-exempt and **not** covered by
    an assertion: a guard cannot search for a string it may not itself hold.
    Nothing here ships; it is test-only, and it is the shortest file in the
    allowlist precisely so that reading it is the audit.

`tests/fixtures/`, `calls.json`, `seen_calls.json` and `digests/` are outside
the scanned extensions anyway. They match only on `cancer` / `oncolog`, which
are real EU call titles inside captured upstream payloads and generated output —
data, not identity. Editing a fixture would corrupt the evidence the
mutation-checked suite is pinned to.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS = ("*.py", "*.ts", "*.tsx", "*.yml", "*.yaml", "*.sql")
SKIP_DIRS = {".git", "node_modules", "dist", "evidence", ".cache", "__pycache__", "digests"}

TENANT = re.compile(r"vertical.?freedom|office@", re.IGNORECASE)

SEED_MIGRATION = "supabase/migrations/0004_seed_vertical_freedom.sql"

# reason: files, not directories. A `tests/` or `supabase/migrations/` skip
# would also exempt conftest.py, the other four migrations and every file added
# to either later — none of which has a justification. Each entry below either
# carries an assertion in this module or is this module.
EXEMPT = {
    SEED_MIGRATION,
    "tests/test_match.py",
    "tests/test_warehouse.py",
    "tests/test_detenanting.py",
}

ASSERTED_EXEMPT_TESTS = ["tests/test_match.py", "tests/test_warehouse.py"]


def scanned_files():
    for pattern in EXTENSIONS:
        for path in ROOT.rglob(pattern):
            if SKIP_DIRS & set(path.relative_to(ROOT).parts):
                continue
            yield path


def tenant_lines(rel):
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        if TENANT.search(line):
            yield number, line


def test_the_scan_actually_reaches_the_source():
    """A guard that silently walks an empty tree passes forever. This pins that
    the walk sees the modules the audit was about — and the migrations, which
    are no longer skipped as a directory."""
    found = {str(p.relative_to(ROOT)) for p in scanned_files()}

    assert "funding_radar.py" in found
    assert "mipe_watch.py" in found
    assert "calls_store.py" in found
    assert "match.py" in found
    assert "warehouse.py" in found
    assert "supabase/migrations/0005_calls_eligible_as.sql" in found
    # reason: the exemption is per file, and the only thing keeping it that way
    # is that the walk still enters these two directories. Adding "tests" or
    # "migrations" to SKIP_DIRS would re-broaden it to everything under them
    # without failing any assertion above.
    assert "tests/test_match.py" in found
    assert "tests/conftest.py" in found
    assert len(found) > 15


def test_no_source_file_names_the_seed_tenant():
    """Test 25 of the plan. It fails the moment a tenant name is pasted back
    into code — which is the only way this audit stays true."""
    offenders = []
    for path in scanned_files():
        rel = str(path.relative_to(ROOT))
        if rel in EXEMPT:
            continue
        for number, line in tenant_lines(rel):
            offenders.append(f"{rel}:{number}: {line.strip()}")

    assert offenders == [], (
        "tenant identity found outside the exempt files:\n  " + "\n  ".join(offenders)
    )


def test_the_exempt_migration_is_the_one_that_holds_the_identity():
    """Stated as an assertion so the exemption above cannot quietly become an
    exemption for a file that no longer carries the row."""
    body = (ROOT / SEED_MIGRATION).read_text(encoding="utf-8")

    assert "'Vertical Freedom'" in body
    assert "insert into public.organizations" in body


@pytest.mark.parametrize("rel", ASSERTED_EXEMPT_TESTS)
def test_the_exempt_tests_name_the_tenant_only_to_assert_its_absence(rel):
    """The body behind the exemption, not a comment claiming one.

    Two shapes are legitimate in a test file that is allowed to hold the name:
    an absence assertion, which must contain the string to search for it, and a
    reference to the seed migration's own filename. Anything else — a docstring
    describing the platform in one tenant's terms, a fixture built from one
    org's identity — is the defect this module exists to catch, and the
    exemption must not cover it."""
    stray = []
    for number, line in tenant_lines(rel):
        legitimate = SEED_MIGRATION.rsplit("/", 1)[-1] in line or "not in" in line
        if not legitimate:
            stray.append(f"{rel}:{number}: {line.strip()}")

    assert stray == [], (
        f"{rel} is exempt only for absence assertions and seed-migration "
        "references; these are neither:\n  " + "\n  ".join(stray)
    )

    # reason: an exemption that outlives its reason is how an allowlist widens.
    # If this file stops naming the tenant, the entry is dead and must go —
    # otherwise it sits there as a live licence for the next paste.
    assert list(tenant_lines(rel)), (
        f"{rel} no longer names the tenant — remove it from EXEMPT"
    )


@pytest.mark.parametrize("module", ["funding_radar", "mipe_watch", "calls_store", "match"])
def test_module_docstrings_are_organisation_agnostic(module):
    """The eight docstrings from the audit describe the single-tenant gate that
    Phase C removed. They were rewritten rather than deleted — each states a
    reason still true of the platform — so this checks the rewrite happened
    rather than that the sentence vanished."""
    text = (ROOT / f"{module}.py").read_text(encoding="utf-8")
    docstring = text.split('"""')[1] if '"""' in text else ""

    assert docstring.strip(), f"{module} lost its module docstring"
    assert not TENANT.search(docstring)
