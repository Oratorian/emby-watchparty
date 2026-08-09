# Contributing to Emby Watch Party

Thank you for your interest in contributing to Emby Watch Party! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Contributions](#submitting-contributions)
- [Style Guidelines](#style-guidelines)
- [Release Process](#release-process)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment. Please:

- Be respectful and considerate in all interactions
- Welcome newcomers and help them get started
- Focus on constructive feedback
- Accept responsibility for mistakes and learn from them

## Getting Started

### Prerequisites

- **Python 3.12**, exactly. `pyproject.toml` pins `requires-python = ">=3.12,<3.13"`, and the lock files are compiled against it. 3.13 will not work.
- **Node.js** 20.19+ or 22.12+ (`package.json` `engines`). CI builds on Node 24.
- Git
- Access to an Emby server for testing

### Development Setup

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/YOUR_USERNAME/emby-watchparty.git
   cd emby-watchparty
   ```

2. **Create a virtual environment**

   Use `.venv` in the repository root. Tooling, CI and the Docker image all assume it.

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

   Confirm you are on the right interpreter before going further, since a system
   `python` on PATH is a common source of confusing failures:

   ```bash
   python --version   # must report 3.12.x
   ```

3. **Install dependencies**

   ```bash
   python -m pip install -r requirements-dev.txt
   ```

   Both requirement files are hash-locked and generated, so do not hand-edit
   them. To add or bump a dependency, edit `requirements.in` (runtime) or
   `requirements-dev.in` (tooling and tests) and recompile:

   ```bash
   uv pip compile requirements.in --universal --generate-hashes --output-file requirements.txt
   uv pip compile requirements-dev.in --universal --generate-hashes --output-file requirements-dev.txt
   ```

   Commit the `.in` and the `.txt` together. `tests/test_dependency_locks.py`
   fails if they drift apart.

4. **Configure the application**

   ```bash
   cp .env.example .env
   # Edit .env with your Emby server details
   ```

   As of 3.0 configuration is environment-only; there is no first-run setup
   page. If boot configuration is invalid the server does not crash and does not
   serve the app. It stays up in unconfigured mode, answers `/api/health` with
   `status=setup_required`, answers `/api/ready` with 503, returns 503 for
   everything else, and prints the failing field names to stderr. If you land
   there, read stderr; it names what is wrong.

   In production, `BEHIND_PROXY` must be declared explicitly, and setting it to
   `true` makes `TRUSTED_PROXY_CIDRS` mandatory. The server refuses to guess its
   own topology, because guessing wrong silently collapses rate limiting into a
   single shared bucket.

5. **Run the backend**

   ```bash
   python -m backend.app
   ```

   This is the supported entry point. `uvicorn backend.app:app` also works;
   the module builds the application lazily on attribute access, so importing
   `backend.app` on its own constructs nothing.

6. **Run the frontend dev server** (separate terminal, for UI work)

   ```bash
   cd frontend
   npm ci
   npm run dev
   ```

   Vite proxies API and Socket.IO traffic to the backend, so keep both running.

## Making Changes

### Keep changes focused

**One issue, or one self-contained feature, per pull request.** This is the
guideline most likely to get a pull request sent back for rework, so please read
it before you start rather than after.

A pull request is too broad when any of the following is true:

- it closes more than one issue
- it mixes a bug fix with a refactor, a dependency bump, or a new feature
- a reviewer cannot hold the whole diff in their head at once

The reason is not tidiness. In a large combined pull request, a weak change
borrows credibility from the strong ones around it, and a change that deserved
its own design discussion gets approved as one bullet in a list of twelve.
Defects that would be obvious in a five-file diff routinely survive a
thirty-file one.

If you have done a lot of work, split it into a stack of pull requests and say
which order they should land in. That is more effort for you and much less for
the reviewer, which is the trade being asked for.

### Branch Naming Convention

Create descriptive branch names following this pattern:

- `feature/short-description` - New features
- `fix/short-description` - Bug fixes
- `docs/short-description` - Documentation changes
- `refactor/short-description` - Code refactoring

Examples:
- `feature/user-avatars`
- `fix/playback-sync-delay`
- `docs/api-documentation`

### Target Branch

Pull requests target the **active integration branch**, not `main`. During the
3.0 cycle that is `3.0-dev`. `main` carries the released stable line and is
protected; it is updated by release merges only.

If you are unsure which branch is current, ask in the issue before you start.

### Commit Messages

Write clear, descriptive commit messages:

- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Fix bug" not "Fixes bug")
- Keep the first line under 72 characters
- Reference issues when applicable

**Good examples:**
```
Add playback progress sync with Emby server

Fix session cookie for reverse proxy deployments

Update README with Docker compose example
```

**Bad examples:**
```
fixed stuff
updates
WIP
```

### Documentation and Changelog

1. **Update documentation** - If your change affects usage, update the README,
   and `docker-compose.yml.example` or `.env.example` if you touched
   configuration.
2. **Add a changelog entry** - Document your change in `CHANGELOG.md` under
   `## [Unreleased]`, in the matching subsection (`Added`, `Changed`, `Fixed`,
   `Removed`). One line, written for a user rather than a reviewer. This is
   checked during review and is easy to forget.

### Generated Files

Three artifact families are generated and verified in CI. If you change their
sources and do not regenerate, the build fails.

- **Deployment artifacts.** After editing `deploy/schema.json` or the deployment
  generator, run `python scripts/generate_deployment_artifacts.py` and commit
  `.env.example`, `docker-compose.yml.example`,
  `docs/deployment/environment.md`, `deploy/casaos/docker-compose.yml`, and
  `deploy/truenas/custom-app.yml`. To check changed, missing, or obsolete output
  without writing, use
  `python scripts/generate_deployment_artifacts.py --check`.

- **Socket event types.** After editing socket event payloads, run
  `python scripts/generate_socket_types.py` and commit the updated
  `backend/socket-events.schema.json` and
  `frontend/src/types/socket.generated.ts`. To check without writing, use
  `python scripts/generate_socket_types.py --check`, which exits non-zero and
  names the stale files.
- **Dependency locks.** See step 3 of Development Setup.

## Testing

There are two obligations here and they are not the same one. The first is
absolute. The second replaces "I did not write tests" with something a reviewer
can actually check.

### 1. Running the existing suite is mandatory

Every pull request must run the full suite locally and have it pass before the
pull request is opened. This is not optional, and "CI will catch it" is not a
substitute; CI is the backstop, not your first run.

**Backend**, from the repository root with `.venv` active:

```bash
python -m ruff check backend scripts tests
python -m ruff format --check backend scripts tests
python -m mypy
python -m pytest
python scripts/generate_socket_types.py --check
```

**Frontend**, from `frontend/`:

```bash
npm ci
npm run lint
npm run type-check
npm run test:unit
npm run build-only
npx playwright install --with-deps chromium webkit   # first run only
npm run test:e2e
```

If something fails for a reason you believe is unrelated to your change, say so
in the pull request and include the output. Do not silently skip it, and do not
disable, `skip`, or loosen an existing test to get a green run. If an existing
test genuinely encodes wrong behaviour, that is a legitimate change, but call it
out explicitly and explain why the old expectation was wrong.

### 2. If nothing in the suite covers your change, test it by hand and write it up

**You are not required to add automated tests.** If no test exists for the area
you touched, you do not have to create one. New tests are welcome and make
review faster, but they are not a condition of acceptance.

What is not acceptable is an untested change. Where the suite cannot prove your
change works, prove it yourself and include a short report in the pull request.

**Test report template:**

```markdown
### Manual test report

**How I tested**
Exact steps someone else could repeat. Include environment: OS, browser and
version, Emby server version, Docker or bare metal, reverse proxy or direct.

**What this covered**
The specific behaviour exercised.

**What this did not cover**
Anything adjacent you did not check. Say so plainly.

**Expected outcome**
What should have happened.

**Actual outcome**
What did happen.
```

Write the report even when the two match. "Expected the departed host to rejoin
their own party; the host rejoined and regained controls" is evidence.
"Tested, works fine" is not, and cannot be reviewed.

Where something genuinely cannot be verified, for example because it needs
hardware or a platform you do not have, say that explicitly under "what this did
not cover" rather than leaving it out. A stated gap can be covered by someone
else. An unstated one ships.

If the actual outcome did not match at first and you then fixed it, keep both in
the report. Knowing what broke and how is useful review context.

### Areas that deserve extra care

- **Multiple users in one party**, including a host who leaves and rejoins
- **Network interruption and reconnect**, not just a clean reload
- **Reverse proxy deployments**, where client IP resolution and cookie flags behave differently from direct access
- **Browser coverage** for UI changes: Chrome, Firefox, Safari and Edge, plus iOS Safari if playback is involved, since iOS uses native HLS rather than hls.js

### Reporting Bugs

Use the GitHub issue templates to report bugs. Include:

- Version of Emby Watch Party
- Emby server version
- Browser and version
- Deployment type (Docker, bare metal, behind a reverse proxy)
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs

## Submitting Contributions

### Pull Request Process

1. **Update your fork**

   Rebase onto the branch you are targeting, not automatically `main`.

   ```bash
   git fetch upstream
   git rebase upstream/3.0-dev
   ```

2. **Push your branch**

   ```bash
   git push origin feature/your-feature
   ```

3. **Open a Pull Request**

   - Use a clear, descriptive title
   - Reference related issues with closing keywords (`Fixes #123`)
   - Describe what changed and why
   - Include screenshots for UI changes
   - Include your test evidence (see [Testing](#testing))

4. **Fill in the template**

   Opening a pull request loads
   [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)
   automatically. It is the checklist form of this document: scope, the suite
   commands, the manual test report, and the documentation items. Work through
   it rather than deleting it.

   The template is deliberately not reproduced here. The copy that used to sit
   in this section drifted out of step with the real file and ended up asking
   contributors to add tests "as needed", which is the opposite of the policy
   above. One authority, in one place; if the template and this document ever
   disagree, this document wins and the disagreement is a bug.

### Review Process

- Maintainers will review your pull request
- Address any requested changes
- Expect questions about scope and about how a change was verified; both are normal and neither implies distrust
- Once approved, your pull request will be merged

## Style Guidelines

The tooling is the authority. The notes below describe intent; `ruff`, `mypy`
and `eslint` decide, and CI runs all three.

### Python

Follow PEP 8, with these project specifics:

- **Formatting**: `ruff format` owns it. Do not hand-format against it.
- **Line length**: 100 characters (`line-length = 100`)
- **Target version**: `py312`
- **Imports**: sorted by ruff (`I`); standard library, third-party, then local
- **Type hints**: expected on new code. mypy runs with `check_untyped_defs`, `no_implicit_optional`, `warn_redundant_casts` and `warn_unused_ignores`.
- **Docstrings**: Google-style

```python
def example_function(param1, param2):
    """Short description of the function.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Description of return value

    Raises:
        ValueError: When something is invalid
    """
    pass
```

If you need a lint suppression, scope it as narrowly as possible and give the
reason in a trailing comment, matching the existing entries in
`[tool.ruff.lint.per-file-ignores]`.

### TypeScript and Vue

Match the existing code; ESLint enforces it (`npm run lint`).

- **Indentation**: 2 spaces
- **Semicolons**: omitted
- **Quotes**: single quotes
- **Components**: `<script setup lang="ts">` single-file components
- **Types**: no `any` in new code. Socket payload types are generated, so import them from `@/types/socket.generated` rather than redeclaring them.

### CSS

- **Indentation**: 2 spaces
- **Scope**: prefer `<style scoped>` inside the component
- **Selectors**: meaningful class names
- **Organization**: group related properties

## Release Process

Releases follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (x.0.0): Breaking changes
- **MINOR** (0.x.0): New features, backward compatible
- **PATCH** (0.0.x): Bug fixes, backward compatible

Version and codename live in `backend/src/__init__.py`, which feeds the startup
banner, `/api/version`, `/api/health`, the OpenAPI title and the frontend
version page. `frontend/package.json` carries a matching version.

### Changelog Format

Follow [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
## [Unreleased]

### Added
- New feature description

### Changed
- Changed behavior description

### Fixed
- Bug fix description

### Removed
- Removed feature description
```

## Questions and Support

- **General questions**: Open a [Question issue](https://github.com/Oratorian/emby-watchparty/issues/new?template=question.yml)
- **Feature requests**: Open a [Feature Request issue](https://github.com/Oratorian/emby-watchparty/issues/new?template=feature_request.yml)
- **Bug reports**: Open a [Bug Report issue](https://github.com/Oratorian/emby-watchparty/issues/new?template=bug_report.yml)

## License

By contributing to Emby Watch Party, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to Emby Watch Party!
