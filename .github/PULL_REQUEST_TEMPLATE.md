<!--
  This template mirrors CONTRIBUTING.md. If the two disagree, CONTRIBUTING.md is
  the authority, and the disagreement is itself worth reporting.
-->

## Summary

<!-- What this changes and why, in a sentence or two. -->

## Changes Made

-
-

## Type of Change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (existing deployments need action)
- [ ] Documentation
- [ ] Refactoring (no functional change)
- [ ] Dependencies

## Scope

<!--
  One issue, or one self-contained feature, per pull request. This is the
  guideline most likely to get a pull request sent back for rework. In a large
  combined change a weak part borrows credibility from the strong parts around
  it, and defects obvious in a five-file diff routinely survive a thirty-file
  one. If you have done a lot of work, split it into a stack of pull requests
  and say which order they should land in.
-->

- [ ] This closes at most one issue, or is one self-contained feature
- [ ] It targets the active integration branch (`3.0-dev`), not `main`

## Testing Done

**Running the existing suite is mandatory.** CI is the backstop, not your first
run. From the repository root with `.venv` active (Python 3.12):

- [ ] `python -m ruff check backend scripts tests`
- [ ] `python -m ruff format --check backend scripts tests`
- [ ] `python -m mypy`
- [ ] `python -m pytest`
- [ ] `python scripts/generate_socket_types.py --check`
- [ ] `python scripts/generate_deployment_artifacts.py --check`

From `frontend/`:

- [ ] `npm run lint`
- [ ] `npm run type-check`
- [ ] `npm run test:unit`
- [ ] `npm run build-only`
- [ ] `npm run test:e2e`

<!--
  If something fails for a reason you believe is unrelated to your change, say
  so here and include the output. Do not silently skip it, and do not disable,
  skip or loosen an existing test to get a green run. If an existing test
  genuinely encodes wrong behaviour, changing it is legitimate, but call it out
  and explain why the old expectation was wrong.
-->

### Manual test report

<!--
  Required wherever nothing in the suite covers your change.

  You are NOT required to write new automated tests. If none exists for the area
  you touched, you do not have to create one; new tests are welcome and make
  review faster, but they are not a condition of acceptance. You ARE required to
  verify the change and show how, so that a reviewer has something to check.

  Fill this in even when expected and actual match. "Expected the departed host
  to rejoin their own party; the host rejoined and regained controls" is
  evidence. "Tested, works fine" is not. Delete this section only when the suite
  genuinely covers the change.
-->

**How I tested**
<!-- Steps someone else could repeat. Include environment: OS, browser and
     version, Emby server version, Docker or bare metal, reverse proxy or
     direct. -->

**What this covered**

**What this did not cover**
<!-- Say so plainly, including anything you could not verify for want of
     hardware or a platform you do not have. A stated gap can be covered by
     someone else; an unstated one ships. -->

**Expected outcome**

**Actual outcome**
<!-- If it did not match at first and you then fixed it, keep both. What broke
     and how is useful review context. -->

## Documentation

- [ ] `CHANGELOG.md` updated under `## [Unreleased]`, in the matching subsection
- [ ] README, `.env.example` or `docker-compose.yml.example` updated, if configuration or usage changed
- [ ] Generated files regenerated and committed, if their sources changed

## Screenshots

<!-- Required for UI changes. Delete this section if it does not apply. -->

## Related Issues

<!-- Use a closing keyword so the issue closes on merge. -->

Fixes #
