CREATE TABLE clinical_entries (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK(kind IN ('self_report','visit')),
    observed_on TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    request_key TEXT NOT NULL UNIQUE,
    encounter_id TEXT UNIQUE REFERENCES encounters(id),
    self_report_id TEXT UNIQUE REFERENCES self_reports(id),
    CHECK((kind='visit' AND encounter_id IS NOT NULL AND self_report_id IS NULL)
       OR (kind='self_report' AND self_report_id IS NOT NULL AND encounter_id IS NULL))
);
CREATE INDEX clinical_entries_timeline ON clinical_entries(patient_id, observed_on, recorded_at);
ALTER TABLE adverse_events ADD COLUMN source_entry_id TEXT REFERENCES clinical_entries(id);
CREATE TRIGGER clinical_entry_author BEFORE INSERT ON clinical_entries BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM users u WHERE u.id=new.actor_id AND u.disabled=0 AND (
            (new.kind='self_report' AND u.role='patient' AND EXISTS (
                SELECT 1 FROM patients p WHERE p.id=new.patient_id AND p.user_id=u.id))
            OR (new.kind='visit' AND u.role='doctor' AND EXISTS (
                SELECT 1 FROM care_relationships r WHERE r.patient_id=new.patient_id
                AND r.doctor_id=u.id AND r.ends_at IS NULL AND r.starts_at<=new.recorded_at))
        )
    ) THEN RAISE(ABORT, 'entry requires authorized author') END;
END;
CREATE TRIGGER clinical_entry_no_update BEFORE UPDATE ON clinical_entries BEGIN SELECT RAISE(ABORT, 'append-only clinical entry'); END;
CREATE TRIGGER clinical_entry_no_delete BEFORE DELETE ON clinical_entries BEGIN SELECT RAISE(ABORT, 'append-only clinical entry'); END;
