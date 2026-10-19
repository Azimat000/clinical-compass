CREATE TABLE first_visit_versions (
    id TEXT PRIMARY KEY NOT NULL,
    visit_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    patient_id TEXT NOT NULL REFERENCES patients(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    recorded_at TEXT NOT NULL,
    protocol_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('draft','completed')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    request_key TEXT NOT NULL UNIQUE,
    UNIQUE(visit_id, revision)
);
CREATE INDEX first_visits_patient ON first_visit_versions(patient_id, recorded_at);
CREATE TRIGGER first_visit_author BEFORE INSERT ON first_visit_versions BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM care_relationships r JOIN users u ON u.id=r.doctor_id
        JOIN patients p ON p.id=r.patient_id
        WHERE r.id=new.relationship_id AND r.patient_id=new.patient_id
        AND u.id=new.actor_id AND u.role='doctor' AND u.disabled=0
        AND r.ends_at IS NULL AND r.starts_at<=new.recorded_at AND p.synthetic=1
    ) THEN RAISE(ABORT, 'first visit requires authorized physician') END;
    SELECT CASE WHEN new.revision != COALESCE((SELECT max(revision)+1 FROM first_visit_versions WHERE visit_id=new.visit_id),1)
        OR EXISTS(SELECT 1 FROM first_visit_versions WHERE visit_id=new.visit_id
            AND (patient_id!=new.patient_id OR state='completed'))
        THEN RAISE(ABORT, 'invalid first visit revision') END;
END;
CREATE TRIGGER first_visit_no_update BEFORE UPDATE ON first_visit_versions BEGIN SELECT RAISE(ABORT, 'append-only first visit'); END;
CREATE TRIGGER first_visit_no_delete BEFORE DELETE ON first_visit_versions BEGIN SELECT RAISE(ABORT, 'append-only first visit'); END;
