# Python Standards

## Language & Runtime
- Python 3.14 (runtime installato), target compatibility 3.11+
- Use `async/await` for all I/O operations (HTTP calls, SMTP)
- Use `httpx.AsyncClient` for HTTP requests (not `requests`)

## Type Hints
- All functions MUST have full type annotations (parameters + return type)
- Use `from __future__ import annotations` at the top of every module
- Prefer `X | None` over `Optional[X]` (PEP 604)
- Use Pydantic `BaseModel` for data validation with `Field()` constraints

## Pydantic v2 Conventions
Source: https://pydantic.dev/docs/validation/latest/concepts/config

- Use `model_config = ConfigDict(...)` for model configuration (not inner `Config` class)
- Use `@field_validator('field_name')` with `@classmethod` for custom validation
- Use `Field(..., ge=0, le=100)` for numeric constraints
- Access field info via `ValidationInfo` in validators

## Naming Conventions
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`

## Code Style (Ruff)
Source: https://github.com/astral-sh/docs/blob/main/site/ruff/tutorial/index.md

- Max line length: 100 characters
- Use `ruff` for linting AND formatting (replaces both flake8 and black)
- Configuration in `pyproject.toml`:
  ```toml
  [tool.ruff]
  line-length = 100

  [tool.ruff.lint]
  select = ["E", "F", "I", "N", "UP", "ANN"]
  # E=pycodestyle, F=pyflakes, I=isort, N=naming, UP=pyupgrade, ANN=annotations

  [tool.ruff.format]
  quote-style = "double"
  indent-style = "space"
  docstring-code-format = true
  ```

## Imports
- Grouped: stdlib → third-party → local (enforced by ruff `I` rules)
- Use relative imports within the `app` package (`from .models import ...`)

## Error Handling
- Use custom exception classes, not bare `Exception`
- Always log errors with context (which operation, what input)
- External service calls: always wrap in try/except with timeout handling

## Dependencies (uv)
Source: https://docs.astral.sh/uv/

- Use `uv` for package management
- `uv init` to initialize project
- `uv add <pkg>` for runtime deps, `uv add --dev <pkg>` for dev deps
- `uv run <command>` to execute within the virtual environment
