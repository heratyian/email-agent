# Email Agent Development Doctrine

This repository follows a Python interpretation of the
[Ruby on Rails Doctrine](https://rubyonrails.org/doctrine). These are working
instructions, not aspirations: use them when designing, implementing, reviewing,
and testing changes.

## Optimize for programmer happiness

Code is read and changed more often than it is written. Make the next person's job
pleasant.

- Prefer clear, unsurprising Python over clever Python.
- Prefer verbose, descriptive variable, method, function, and class names over
  acronyms, abbreviations, and shorthand.
- Name things for their domain meaning. Use `configured_account`,
  `processing_failure`, and `message_identifier`, not `cfg`, `err`, or `msg_id`.
- A reader should understand the main path without mentally expanding names,
  decoding indirection, or jumping through several files.
- Optimize for a smooth local workflow: focused tests, useful errors, and commands
  that behave consistently.

## Convention over configuration

Follow the repository's established structure unless the existing convention is
the problem being fixed.

- `config/` defines and loads configuration.
- `providers/` adapts Gmail and IMAP behavior.
- `db/` owns persistence and migrations.
- `services/` owns provider-independent application workflows.
- `ai/` owns bounded model construction, prompts, and structured model calls.
- `cli/` owns command line interface and presentation.

Use existing factories, services, models, and rendering conventions before adding
new configuration switches or parallel abstractions. Defaults should serve the
normal case without additional setup.

## Offer a curated menu

Choose a strong default approach for each problem instead of supporting many
equivalent patterns.

- Use `uv` for dependency and command execution, Ruff for linting, pytest for tests,
  Typer for command declarations, Pydantic for validated data, and SQLite through
  the existing database layer.
- Reuse the current dependency set when it solves the problem adequately.
- Add a dependency only when it removes meaningful complexity and earns its ongoing
  maintenance cost.
- Do not add extension points, strategy classes, plugin systems, feature flags, or
  configuration merely in anticipation of a possible future need.

## Use the paradigm that makes the code clearest

No single programming style is mandatory.

- Use dataclasses and Pydantic models for explicit data with meaningful fields.
- Use classes when identity, state, or a coherent set of operations benefits from
  them.
- Use small functions for transformations and straightforward orchestration.
- Use comprehensions when they remain immediately readable; use ordinary loops when
  the logic needs names, branching, or explanation.
- Prefer composition and direct calls over inheritance, metaprogramming, decorators,
  registries, or dependency-injection frameworks.
- Keep interfaces typed at important boundaries. Do not create protocols or generic
  abstractions until at least two real implementations need the same contract.

## Exalt readable, beautiful code

Beautiful code in this application is explicit, cohesive, and calm.

- Optimize for simplicity and readability before brevity or reuse.
- Keep the happy path visually obvious. Handle errors near the operation that can
  fail without burying the main behavior.
- Prefer guard clauses over deeply nested conditionals.
- Prefer domain-specific names over comments that explain vague names.
- Keep methods focused, but do not split a readable operation into tiny forwarding
  methods merely to reduce line count.
- Remove duplication when the shared concept is stable and has a clear name. A few
  repeated readable lines are better than a premature abstraction.
- Avoid boolean parameters when a descriptive method name, enum, or small value
  object would make the call site clearer.
- Comments should explain why a decision exists, especially a safety constraint or
  provider quirk. Do not narrate what readable code already says.
- Match surrounding style and let Ruff enforce mechanical formatting.

## Trust developers with sharp tools, and preserve safety boundaries

Powerful operations are acceptable when their scope and consequences are explicit.
This application handles private email, so trust must coexist with strict product
safety.

- Never add an email send path. Email Agent may generate and upload drafts only.
- Keep provider calls, persistence, retries, loops, and side effects in deterministic
  Python services.
- Models may provide bounded judgment through validated structured output. They must
  not receive provider objects, database handles, credentials, or write-capable
  tools.
- Explicit slash commands may perform their documented effects. Natural-language
  deletion and external mailbox writes require confirmation immediately before the
  write.
- Preserve per-message failure isolation and idempotent mailbox behavior.
- Regenerating a suggestion may replace only a pending local suggestion. It must not
  alter an uploaded mailbox draft.
- Never log credentials, tokens, or OAuth secrets. Exact message, prompt, and model
  content may be logged only when model tracing is explicitly enabled.
- Keep account boundaries explicit and validate that account-scoped resources belong
  to the active or requested account.

## Value the integrated application

Email Agent is one understandable Python application, not a collection of miniature
frameworks or services.

- Keep the CLI, interactive shell, services, providers, model integration, and
  persistence in this repository unless a real operational constraint requires a
  boundary.
- Typer commands and the shell must call the same command handlers and application
  services.
- Chat is an interface, not the architecture. Parse input into typed, validated
  commands before deterministic execution.
- Prefer an in-process method call over queues, subprocesses, RPC, or network service
  boundaries.
- Keep runtime construction centralized in `RuntimeFactory`.
- Services must not import CLI code or terminal rendering.

## Prefer progress over accidental compatibility

Improve the design when the benefit is clear, while protecting documented behavior
and stored user data.

- Preserve existing CLI commands, safety guarantees, and scriptable output unless a
  change explicitly revises them.
- Make database changes through ordered, transactional migrations. Never assume a
  fresh database.
- Prefer a direct migration and cleanup over maintaining two architectures
  indefinitely.
- Do not keep obsolete aliases, compatibility branches, or abstractions without a
  demonstrated user need.
- Make risky changes in reviewable phases. Establish deterministic behavior and tests
  before adding model-based judgment.

## Keep a big tent

Make the project approachable to Python developers who did not design it.

- Use standard Python vocabulary and familiar constructs.
- Write errors that explain what the user can do next without exposing internals or
  secrets.
- Add focused tests that demonstrate behavior rather than mirroring implementation.
- Respect well-reasoned alternatives, but converge on one repository convention after
  a decision is made.
- Improve nearby confusing names and documentation when doing so is safe and tightly
  related to the task.

## Working agreement

Before considering a change complete:

1. Confirm the implementation is the simplest design that clearly meets the current
   requirement.
2. Check that names are descriptive and contain no unnecessary acronyms or shorthand.
3. Preserve deterministic ownership of side effects and all email safety boundaries.
4. Add or update tests at the narrowest useful level.
5. Run:

   ```bash
   uv run ruff check .
   uv run pytest
   git diff --check
   ```

6. Review the diff for unnecessary files, abstractions, dependencies, configuration,
   and comments.
