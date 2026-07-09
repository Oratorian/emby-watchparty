# Contributing to Emby Watch Party

Thank you for your interest in contributing to Emby Watch Party! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Submitting Contributions](#submitting-contributions)
- [Style Guidelines](#style-guidelines)
- [Testing](#testing)
- [Release Process](#release-process)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment. Please:

- Be respectful and considerate in all interactions
- Welcome newcomers and help them get started
- Focus on constructive feedback
- Accept responsibility for mistakes and learn from them

## Getting Started

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git
- Access to an Emby server for testing

### Development Setup

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/YOUR_USERNAME/emby-watchparty.git
   cd emby-watchparty
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure the application**

   ```bash
   cp .env.example .env
   # Edit .env with your Emby server details
   ```

5. **Run the development server**

   ```bash
   python app.py
   ```

   The application will be available at `http://localhost:5000`

## Making Changes

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

### Code Changes

1. **Keep changes focused** - One feature or fix per pull request
2. **Update documentation** - If your change affects usage, update the README
3. **Add changelog entry** - Document your changes in CHANGELOG.md under "Unreleased"

## Submitting Contributions

### Pull Request Process

1. **Update your fork**

   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Push your branch**

   ```bash
   git push origin feature/your-feature
   ```

3. **Open a Pull Request**

   - Use a clear, descriptive title
   - Reference any related issues
   - Describe what changes you made and why
   - Include screenshots for UI changes

4. **PR Template**

   ```markdown
   ## Summary
   Brief description of changes

   ## Changes Made
   - Change 1
   - Change 2

   ## Testing Done
   How you tested the changes

   ## Related Issues
   Fixes #123
   ```

### Review Process

- Maintainers will review your PR
- Address any requested changes
- Once approved, your PR will be merged

## Style Guidelines

### Python Code Style

Follow PEP 8 guidelines with these specifics:

- **Indentation**: 4 spaces (no tabs)
- **Line length**: Maximum 100 characters
- **Imports**: Group in order - standard library, third-party, local
- **Docstrings**: Use Google-style docstrings

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

### JavaScript Code Style

- **Indentation**: 4 spaces
- **Semicolons**: Required
- **Quotes**: Single quotes preferred
- **Comments**: Use JSDoc for functions

### CSS Code Style

- **Indentation**: 4 spaces
- **Selectors**: Use meaningful class names
- **Organization**: Group related properties

## Testing

### Manual Testing

Before submitting a PR, test your changes:

1. **Basic functionality**
   - Application starts without errors
   - Can create and join watch parties
   - Playback synchronization works

2. **Browser compatibility**
   - Test in Chrome, Firefox, Safari, and Edge
   - Check mobile browsers if applicable

3. **Edge cases**
   - Multiple users in a party
   - Network interruptions
   - Invalid inputs

### Reporting Bugs

Use the GitHub issue templates to report bugs. Include:

- Version of Emby Watch Party
- Emby server version
- Browser and version
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs

## Release Process

Releases follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (x.0.0): Breaking changes
- **MINOR** (0.x.0): New features, backward compatible
- **PATCH** (0.0.x): Bug fixes, backward compatible

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
