# AGENTS.md

## Commands

- **Run bot:** `python -m src.bot`
- **Run all tests:** `python -m unittest discover tests/`
- **Run single test file:** `python -m unittest tests.test_agent_llm_routing`
- **Run single test case:** `python -m unittest tests.test_agent_llm_routing.BuildLlmRoutingTests.test_opencode_claude_uses_anthropic_client_and_endpoint`
- **Install deps:** `pip install -r requirements.txt && playwright install chromium`
- **Docker:** `docker compose up -d` / `docker compose logs -f`

## Code Style

- **Language:** Python 3.12+; use modern union syntax (`str | None`) over `Optional[str]`
- **Types:** Add type annotations to all function signatures and return types
- **Imports:** Standard library → third-party → local (`src.*`), each group separated by a blank line
- **Naming:** `snake_case` for variables/functions/modules, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants
- **Settings:** All configuration via `src/config.py` (`pydantic-settings`); never hardcode secrets — read from `.env`
- **Error handling:** Use specific exception types; log errors with context rather than silently swallowing them
- **Testing:** Use `unittest.TestCase`; patch external dependencies via `sys.modules` in `setUp`/`tearDown` (no third-party mock libs); keep tests isolated and deterministic
- **No formatter/linter is configured** — follow PEP 8 manually (4-space indent, max ~100 chars/line)

## Commit Conventions

Group changes into meaningful commits before hand-off. Each commit should:
- Represent a single logical change
- Have a descriptive commit message
- Be self-contained and functional
