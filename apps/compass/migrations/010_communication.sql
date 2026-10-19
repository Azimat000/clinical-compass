CREATE TABLE message_context (
 message_id TEXT PRIMARY KEY REFERENCES messages(id), recipient_id TEXT NOT NULL REFERENCES users(id),
 entry_id TEXT REFERENCES clinical_entries(id), task_id TEXT REFERENCES adherence_tasks(id)
);
CREATE TABLE message_receipts (
 message_id TEXT NOT NULL REFERENCES messages(id), kind TEXT NOT NULL CHECK(kind IN ('received','read')),
 actor_id TEXT NOT NULL REFERENCES users(id), occurred_at TEXT NOT NULL, PRIMARY KEY(message_id,kind)
);
CREATE TABLE adherence_tasks (
 id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id),
 relationship_id TEXT NOT NULL REFERENCES care_relationships(id), action_id TEXT NOT NULL REFERENCES care_actions(id),
 label TEXT NOT NULL, due_at TEXT NOT NULL, created_at TEXT NOT NULL, doctor_id TEXT NOT NULL REFERENCES users(id),
 request_key TEXT NOT NULL UNIQUE
);
CREATE TABLE adherence_entries (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES adherence_tasks(id), actor_id TEXT NOT NULL REFERENCES users(id),
 outcome TEXT NOT NULL CHECK(outcome IN ('taken','missed','unknown','conflicting')),
 reason TEXT NOT NULL, recorded_at TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE
);
CREATE TRIGGER message_no_update BEFORE UPDATE ON messages BEGIN SELECT RAISE(ABORT,'immutable message'); END;
CREATE TRIGGER message_no_delete BEFORE DELETE ON messages BEGIN SELECT RAISE(ABORT,'immutable message'); END;
CREATE TRIGGER task_no_update BEFORE UPDATE ON adherence_tasks BEGIN SELECT RAISE(ABORT,'immutable task'); END;
CREATE TRIGGER task_no_delete BEFORE DELETE ON adherence_tasks BEGIN SELECT RAISE(ABORT,'immutable task'); END;
CREATE TRIGGER adherence_entry_no_update BEFORE UPDATE ON adherence_entries BEGIN SELECT RAISE(ABORT,'immutable adherence entry'); END;
CREATE TRIGGER adherence_entry_no_delete BEFORE DELETE ON adherence_entries BEGIN SELECT RAISE(ABORT,'immutable adherence entry'); END;
CREATE TRIGGER receipt_no_update BEFORE UPDATE ON message_receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
CREATE TRIGGER receipt_no_delete BEFORE DELETE ON message_receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
CREATE TRIGGER context_no_update BEFORE UPDATE ON message_context BEGIN SELECT RAISE(ABORT,'immutable context'); END;
CREATE TRIGGER context_no_delete BEFORE DELETE ON message_context BEGIN SELECT RAISE(ABORT,'immutable context'); END;
