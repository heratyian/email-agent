from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from email_agent.models import Draft, DraftReply, EmailClassification, EmailMessage


@dataclass
class ProcessedEmail:
    local_id: int
    message: EmailMessage
    classification: EmailClassification
    reply: DraftReply | None
    draft: Draft | None


class EmailPipeline:
    def __init__(self, profile, provider, agents, database):
        self.profile, self.provider, self.agents, self.database = (
            profile,
            provider,
            agents,
            database,
        )

    def process(self, limit: int = 20) -> list[ProcessedEmail]:
        results = []
        for message in self.provider.get_new_messages(limit):
            if self.database.is_processed(message.account_id, message.provider_id):
                continue
            started = perf_counter()
            thread = self.provider.get_thread(message.provider_id)
            classification = self.agents.classify(message, thread)
            reply = None
            if classification.requires_reply and self.profile.safety.allow_drafts:
                reply = self.agents.draft(message, thread, classification)
                words = reply.body.split()
                if len(words) > self.profile.behavior.max_reply_words:
                    reply.body = " ".join(words[: self.profile.behavior.max_reply_words])
            local_id, draft = self.database.save_result(message, classification, reply)
            self.database.record_run(
                local_id, self.profile, round((perf_counter() - started) * 1000), bool(reply)
            )
            self.provider.mark_processed(message.provider_id)
            results.append(ProcessedEmail(local_id, message, classification, reply, draft))
        return results
