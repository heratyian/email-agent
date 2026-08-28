-- Generated from email_agent.db.models. Do not edit independently.

CREATE TABLE "messages" (
    "id" INTEGER NOT NULL PRIMARY KEY,
    "account_id" TEXT NOT NULL,
    "provider_message_id" TEXT NOT NULL,
    "thread_id" TEXT,
    "from_address" TEXT NOT NULL,
    "from_name" TEXT,
    "subject" TEXT NOT NULL,
    "text_body" TEXT,
    "received_at" DATETIME NOT NULL,
    "provider_mailbox" TEXT NOT NULL,
    "provider_uid" TEXT NOT NULL
);
CREATE UNIQUE INDEX "messages_account_id_provider_message_id"
    ON "messages" ("account_id", "provider_message_id");

CREATE TABLE "category_syncs" (
    "id" INTEGER NOT NULL PRIMARY KEY,
    "message_id" INTEGER NOT NULL,
    "destination" TEXT NOT NULL,
    "synced_at" DATETIME NOT NULL,
    "provider_uid" TEXT,
    "provider_mailbox" TEXT,
    "active" INTEGER NOT NULL,
    FOREIGN KEY ("message_id") REFERENCES "messages" ("id")
);
CREATE INDEX "category_syncs_message_id" ON "category_syncs" ("message_id");
CREATE UNIQUE INDEX "category_syncs_message_id_destination"
    ON "category_syncs" ("message_id", "destination");

CREATE TABLE "triages" (
    "id" INTEGER NOT NULL PRIMARY KEY,
    "message_id" INTEGER NOT NULL,
    "category" TEXT,
    "requires_reply" INTEGER NOT NULL,
    "priority" TEXT NOT NULL,
    "intent" TEXT,
    "summary" TEXT NOT NULL,
    "confidence" REAL NOT NULL,
    "requires_escalation" INTEGER NOT NULL,
    "escalation_reason" TEXT,
    "category_sync_pending" INTEGER NOT NULL,
    FOREIGN KEY ("message_id") REFERENCES "messages" ("id")
);
CREATE UNIQUE INDEX "triages_message_id" ON "triages" ("message_id");

CREATE TABLE "drafts" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "message_id" INTEGER NOT NULL,
    "recipient" TEXT NOT NULL,
    "subject" TEXT NOT NULL,
    "body" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "reasoning_summary" TEXT NOT NULL,
    "confidence" REAL NOT NULL,
    "requires_escalation" INTEGER NOT NULL,
    "escalation_reason" TEXT,
    "created_at" DATETIME NOT NULL,
    FOREIGN KEY ("message_id") REFERENCES "messages" ("id")
);
CREATE INDEX "drafts_message_id" ON "drafts" ("message_id");
