# Testing Strategy

## Framework & Tools
- `pytest` for test execution
- `hypothesis` for property-based tests
- `pytest-asyncio` for async test support
- `httpx` for API integration tests (via `TestClient`)

## Pytest Configuration
Source: https://github.com/pytest-dev/pytest/blob/main/doc/en/reference/customize.rst

```toml
[tool.pytest]
minversion = "9.0"
addopts = ["-ra", "-q"]
testpaths = ["tests"]
```

## Test Structure
```
tests/
├── __init__.py
├── test_calculation_service.py   # Property tests + unit tests for formulas
├── test_config_service.py        # Property test for config validation
├── test_route_adapter.py         # Property test for distance decomposition + mocks
├── test_adapters.py              # Unit tests for ORS/SMTP adapters (mocked)
├── test_api.py                   # API endpoint integration tests
```

## Property-Based Tests (Hypothesis)
Source: https://hypothesis.readthedocs.io/

- Minimum 100 examples per property: `@settings(max_examples=100)`
- Tag format in docstring: `# Feature: transport-quote-calculator, Property N: title`
- Properties to validate:
  1. Route distance decomposition (highway + regular = total)
  2. Fuel cost formula correctness
  3. Toll cost formula correctness
  4. Quote total = fuel + toll
  5. Config validation (in-range accepted, out-of-range defaults)

## Naming Convention
- Test files: `test_<module>.py`
- Test functions: `test_<what_is_being_tested>`
- Property tests: `test_property_<property_name>`

## Running Tests
- All tests: `uv run pytest`
- Single file: `uv run pytest tests/test_calculation_service.py`
- Verbose: `uv run pytest -v`
- Stop at first failure: `uv run pytest -x`

## Mocking
- External APIs (ORS, SMTP): always mocked in unit tests
- Use `unittest.mock.AsyncMock` for async adapters
- Integration tests with real ORS: limited to 2-3 fixed routes
