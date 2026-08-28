# AGENT.md

Give direct, unsentimental feedback. Avoid praise, superlatives, and reflexive agreement.

Follow the [Ruby on Rails Doctrine](https://rubyonrails.org/doctrine), adapted to Python:

- optimize for programmer happiness
- convention over configuration
- strong defaults
- human readable code
- an integrated application
- progress over compatibility
- approachability

## Code

- Prefer simple, explicit, unsurprising Python over cleverness, indirection, or premature abstraction.
- Code should be self-documenting. Use docstrings liberally. Use Simplified Technical English for documentation.
- Use descriptive domain names; avoid acronyms, abbreviations, and shorthand.
- Name structured model output schemas with an `Output` suffix.
- Keep the happy path obvious. Prefer guard clauses and local error handling.
- Use functions, classes, dataclasses, Pydantic models, comprehensions, and loops where each is clearest.
- Abstract only stable concepts with multiple real uses. Readable duplication is acceptable.
- Match existing conventions and let Ruff handle formatting.

## Architecture

- Follow architectural best practices. Aim for simplicity and predictable patterns.
- Rich Domain Model. Put business logic directly inside models rather than creating separate, abstract service objects. (Domain Driven Design)
- Follow existing structure and reuse existing abstractions. Suggest refactors when it  improves human readability and/or performance.
- Keep this a single understandable Python application.
- It's preferable to use a library than roll our own solution to a solved problem. Reuse dependencies when possible. Add dependencies when it meaningfully reduces complexity.
- Do not add code for hypothetical needs.

## Changes

Before finishing:

1. Remove unnecessary complexity, files, dependencies, configuration, comments, and abstractions.
2. Check names for clarity and unnecessary shorthand.
3. Add/update the narrowest useful tests.
4. Run:

   ```bash
   uv run ruff check .
   uv run pytest
   git diff --check
   ```
5. Review the final diff
