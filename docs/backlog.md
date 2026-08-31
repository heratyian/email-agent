# What I would improve

The current application proves the end-to-end workflow. These are the next
improvements I would make, in priority order.

## Correctness and architecture

1. **Apply exact search filters before semantic ranking.** A bounded vector
   candidate window can currently exclude a valid exact match.
2. **Separate mailbox organization from local triage.** Triage should save local
   analysis independently from the optional Gmail label or IMAP folder change.
   This would make the side-effect boundary and retry behavior clearer.
3. **Make draft upload idempotent.** A retry should not create a duplicate mailbox
   draft when the provider succeeds but local persistence fails.
4. **Synchronize existing provider categories.** Import Gmail labels or IMAP
   folders when configuring categories instead of requiring users to reproduce
   the provider taxonomy manually.

## Evaluation and prompting

1. **Evaluate complete LangGraph conversations.** Run multi-turn tests that
   include tool calls, message references, confirmation, cancellation, and state
   updates instead of evaluating only assistant routing.
2. **Expand search-plan evaluation.** The current evaluation checks structured
   planner fields. Add more cases for semantic-query quality, explicit versus
   inferred filters, and compound constraints.
3. **Add evaluation profiles for other users.** A customer-support profile should
   have its own prompts, categories, corpus, expected decisions, and draft-quality
   criteria.
4. **Add business context to specialized prompts.** A customer-support agent
   should receive relevant company policies, products, tone guidance, and
   escalation rules.
5. **Improve natural-language interpretation.** Expand regression cases for
   ambiguous references, corrections, compound requests, and follow-up turns.

## Configuration and product experience

1. **Configure models by capability.** Triage, drafting, search planning, and
   conversational routing should be able to use different models when quality,
   latency, or cost requirements differ.
2. **Stream long-running work.** Report progress during triage, search, and draft
   generation instead of waiting for a complete result.
3. **Improve terminal feedback.** Add timers, spinners, and loading indicators
   where they clarify model or provider latency without making logs noisy.
4. **Add an 'unsubscribe from newsletter' workflow.** Provide a tool that finds and
   executes supported unsubscribe actions.
