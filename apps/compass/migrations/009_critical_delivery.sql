CREATE TABLE critical_delivery (
    event_id TEXT PRIMARY KEY REFERENCES critical_events(id),
    ready_at TEXT NOT NULL,
    received_at TEXT,
    seen_at TEXT,
    acknowledged_at TEXT,
    reacted_at TEXT,
    reaction TEXT,
    reserve_attempts INTEGER NOT NULL DEFAULT 0,
    reserve_after TEXT NOT NULL,
    reserve_token TEXT,
    reserve_state TEXT NOT NULL DEFAULT 'pending' CHECK(reserve_state IN ('pending','leased','operator_received','dead')),
    CHECK(seen_at IS NULL OR received_at IS NOT NULL),
    CHECK(acknowledged_at IS NULL OR seen_at IS NOT NULL),
    CHECK(reacted_at IS NULL OR (acknowledged_at IS NOT NULL AND length(reaction)>0))
);
CREATE TABLE critical_delivery_log (
    sequence INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES critical_events(id),
    actor_id TEXT REFERENCES users(id),
    action TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER critical_delivery_log_no_update BEFORE UPDATE ON critical_delivery_log BEGIN SELECT RAISE(ABORT,'immutable delivery log'); END;
CREATE TRIGGER critical_delivery_log_no_delete BEFORE DELETE ON critical_delivery_log BEGIN SELECT RAISE(ABORT,'immutable delivery log'); END;
