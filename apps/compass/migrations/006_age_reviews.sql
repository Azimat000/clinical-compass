CREATE TABLE age_reviews (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    recorded_at TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    basis TEXT NOT NULL CHECK(length(trim(basis)) > 0),
    sources_json TEXT NOT NULL CHECK(json_valid(sources_json)),
    sources_fingerprint TEXT NOT NULL,
    request_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
CREATE INDEX age_reviews_patient ON age_reviews(patient_id);
CREATE TRIGGER age_reviews_no_update BEFORE UPDATE ON age_reviews
BEGIN SELECT RAISE(ABORT, 'immutable age review'); END;
CREATE TRIGGER age_reviews_no_delete BEFORE DELETE ON age_reviews
BEGIN SELECT RAISE(ABORT, 'immutable age review'); END;
