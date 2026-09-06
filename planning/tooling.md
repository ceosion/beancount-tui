# Tooling (`TOOL`)

Project infrastructure, not user-facing features.

---

### TOOL-01: Textual snapshot tests

- **Status:** done
- **Depends on:** none
- **Effort:** 1.5h

**Description:** Add `pytest-textual-snapshot` (dev dependency) and baseline
snapshots for the main screen and each modal (transaction form, directive
form, confirm dialog, income statement), to catch visual regressions that
functional tests miss.

**Acceptance criteria:**
- [x] `pytest-textual-snapshot` added to the dev dependency group.
- [x] Baseline snapshots committed for the main screen and every existing
      modal screen.
- [x] CI runs snapshot tests and fails on unreviewed diffs.
- [x] `README`/`CLAUDE.md` note how to regenerate snapshots after an
      intentional UI change.

---

### TOOL-02: Python version matrix in CI

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** Extend the CI workflow to run the test suite (and lint)
against Python 3.11, 3.12, and 3.13 instead of only the runner default,
per the project's stated `3.11+` support.

**Acceptance criteria:**
- [x] CI matrix runs `pytest` and `ruff check` on 3.11, 3.12, and 3.13.
- [x] Any version-specific failures surfaced by the matrix are fixed or
      explicitly documented as known gaps.

**Notes:** `.github/workflows/ci.yml`'s `test` job now runs a
`strategy.matrix.python-version: ["3.11", "3.12", "3.13"]`, pinning each
via `astral-sh/setup-uv@v5`'s `python-version` input (which sets
`UV_PYTHON` for the rest of the job, overriding the interpreter `uv sync`/
`uv run` would otherwise pick). `fail-fast: false` is set so a failure on
one version doesn't hide results from the others. Verified locally with
`uv run --python {3.11,3.12,3.13} pytest -q` and
`uv run --python {3.11,3.12,3.13} ruff check .` — all 74 tests and lint
pass cleanly on every version; no version-specific failures were found,
so nothing needed to be fixed or documented as a known gap.

---

### TOOL-03: Coverage reporting

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** Run pytest with `--cov` in CI, upload/report the result,
and fail the build below a threshold once a baseline is established from
the current suite.

**Acceptance criteria:**
- [x] CI runs tests with coverage and reports the percentage (job summary or
      uploaded artifact).
- [x] A minimum-coverage threshold is enforced, set at or slightly below the
      baseline measured when this task lands.

---

### TOOL-04: Package and publish

- **Status:** blocked — awaiting PyPI credentials
- **Depends on:** none
- **Effort:** 1.5h

**Description:** Fill out `pyproject.toml` project metadata (classifiers,
project URLs, license), add a `CHANGELOG.md`, and publish to PyPI so
`uvx beancount-tui` works for end users instead of requiring a source
checkout.

**Acceptance criteria:**
- [x] `pyproject.toml` has classifiers, homepage/repository URLs, and a
      license field.
- [x] `CHANGELOG.md` exists with at least a first-release entry.
- [ ] Package published to PyPI; `uvx beancount-tui --help` works from a
      clean environment.

Note: actual publishing to PyPI requires a human with real PyPI credentials
(API token / trusted-publisher setup) to run; it was intentionally left
undone here.
