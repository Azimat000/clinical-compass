CREATE TABLE routine_notifications (
    id TEXT PRIMARY KEY NOT NULL,
    entry_id TEXT NOT NULL UNIQUE REFERENCES clinical_entries(id),
    event_id TEXT NOT NULL UNIQUE REFERENCES outbox_events(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    recipient_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    ready_at TEXT,
    delivered_at TEXT,
    seen_at TEXT,
    acknowledged_at TEXT,
    CHECK(delivered_at IS NULL OR ready_at IS NOT NULL),
    CHECK(seen_at IS NULL OR delivered_at IS NOT NULL),
    CHECK(acknowledged_at IS NULL OR seen_at IS NOT NULL)
);
CREATE INDEX routine_recipient ON routine_notifications(recipient_id, created_at);
CREATE TABLE outbox_attempts (
    event_id TEXT NOT NULL REFERENCES outbox_events(id),
    attempt INTEGER NOT NULL CHECK(attempt > 0),
    attempted_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('processed','retry','dead')),
    error TEXT,
    PRIMARY KEY(event_id, attempt)
);
CREATE TRIGGER attempts_immutable_update BEFORE UPDATE ON outbox_attempts BEGIN
    SELECT RAISE(ABORT, 'Attempt history is immutable');
END;
CREATE TRIGGER attempts_immutable_delete BEFORE DELETE ON outbox_attempts BEGIN
    SELECT RAISE(ABORT, 'Attempt history is immutable');
END;
