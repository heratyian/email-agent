from email_agent.config import AgentConfig
from email_agent.db.repositories.base import ConnectionContext


class ProcessingRunRepository:
    """Record model runs for processing diagnostics and audit history."""

    def __init__(self, connect: ConnectionContext):
        self.connect = connect

    def record(
        self,
        message_id: int,
        account_id: str,
        agent: AgentConfig,
        latency_ms: int,
        drafted: bool,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_runs(
                       message_id,account_id,model,latency_ms,draft_generated,error
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    message_id,
                    account_id,
                    f"{agent.model.provider}:{agent.model.model}",
                    latency_ms,
                    drafted,
                    error,
                ),
            )
