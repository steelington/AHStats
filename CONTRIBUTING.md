# Contributing to AHSTATS

Thank you for your interest in contributing to AHSTATS!

## Development Setup

1. **Fork the repository**
   ```bash
   git clone https://github.com/yourusername/ahstats.git
   cd ahstats
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

4. **Run the application**
   ```bash
   python app.py
   ```

## Running Tests

```bash
python -m tests
```

All tests should pass before submitting a pull request.

## Code Style

- Follow [PEP 8](https://pep8.org/) Python style guide
- Use type hints where possible
- Add docstrings to public functions and classes
- Keep functions focused and small (ideally under 50 lines)
- Use descriptive variable names

## Architecture Guidelines

- **gui.py**: UI code only - keep business logic separate
- **db.py**: All database operations must use the `@_locked` decorator
- **parser.py**: Pure functions - no side effects
- **sync.py**: Orchestration layer - coordinates client + db + parser
- **client.py**: HTTP only - no parsing or business logic

See [CLAUDE.md](CLAUDE.md) for detailed architecture notes.

## Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write clear, focused commits
   - Add tests for new functionality
   - Update documentation if needed

3. **Test your changes**
   ```bash
   python -m tests
   python app.py  # Manual testing
   ```

4. **Commit with clear messages**
   ```bash
   git commit -m "Add feature: description of what you added"
   ```

5. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Open a pull request**
   - Describe what your PR does
   - Reference any related issues
   - Include screenshots for UI changes

## Reporting Bugs

Use the [GitHub issue tracker](https://github.com/yourusername/ahstats/issues). Include:

- **Python version**: `python --version`
- **OS**: Windows 10/11, macOS, Linux distribution
- **Steps to reproduce**: Numbered list
- **Expected behavior**: What should happen
- **Actual behavior**: What actually happened
- **Logs**: Relevant entries from `ahstats.log`

## Feature Requests

Open an issue with the "enhancement" label. Describe:

- **Use case**: Why is this feature needed?
- **Proposed solution**: How should it work?
- **Alternatives considered**: Other approaches you've thought about

## Database Changes

If you modify the database schema:

1. Update `SCHEMA` constant in `db.py`
2. Consider migration path for existing databases
3. Update relevant methods in `StatsDB` class
4. Add tests for new queries
5. Document changes in PR description

## Parser Changes

If you modify HTML parsers:

1. Add/update test fixtures in `tests/fixtures/`
2. Add test cases in `tests/test_parser.py`
3. Handle edge cases (missing data, unexpected formats)
4. Log warnings for unexpected HTML structures

## Rate Limiting

**CRITICAL**: Never reduce the 3-second delay in `client.py`. This prevents IP blocking from HiTech's servers. Contributions that bypass rate limiting will be rejected.

## Code of Conduct

- Be respectful and constructive
- Focus on the code, not the person
- Help others learn and grow
- Assume good intentions

## Questions?

- Read [CLAUDE.md](CLAUDE.md) for architecture details
- Check existing issues and pull requests
- Open a discussion issue for big changes before coding

Thank you for contributing!
