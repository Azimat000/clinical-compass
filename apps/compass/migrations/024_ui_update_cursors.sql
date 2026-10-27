-- Operational cursor only; all clinical histories remain append-only.
CREATE TABLE backend_ui_update_cursors (
 patient_id TEXT NOT NULL REFERENCES patients(id),
 relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
 operation TEXT NOT NULL CHECK(operation IN ('diagnosis','plan')),
 fingerprint TEXT NOT NULL,
 status TEXT NOT NULL,
 run_id TEXT REFERENCES analysis_runs(id),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(patient_id,relationship_id,operation)
);
