CREATE TABLE text_imports (
 id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id),
 relationship_id TEXT NOT NULL REFERENCES care_relationships(id), doctor_id TEXT NOT NULL REFERENCES users(id),
 source_text TEXT NOT NULL, source_sha256 TEXT NOT NULL, result_json TEXT NOT NULL,
 created_at TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE
);
CREATE TABLE extraction_reviews (
 id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES text_imports(id),
 doctor_id TEXT NOT NULL REFERENCES users(id), payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE
);
CREATE TRIGGER import_no_update BEFORE UPDATE ON text_imports BEGIN SELECT RAISE(ABORT,'immutable import'); END;
CREATE TRIGGER import_no_delete BEFORE DELETE ON text_imports BEGIN SELECT RAISE(ABORT,'immutable import'); END;
CREATE TRIGGER extraction_review_no_update BEFORE UPDATE ON extraction_reviews BEGIN SELECT RAISE(ABORT,'immutable review'); END;
CREATE TRIGGER extraction_review_no_delete BEFORE DELETE ON extraction_reviews BEGIN SELECT RAISE(ABORT,'immutable review'); END;
