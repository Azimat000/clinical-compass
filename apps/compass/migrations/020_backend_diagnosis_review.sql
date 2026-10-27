-- Physician review is separate from treatment confirmation and model results.
CREATE TABLE backend_diagnosis_reviews (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    version INTEGER NOT NULL CHECK(version>0),
    previous_id TEXT REFERENCES backend_diagnosis_reviews(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    request_key TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    run_id TEXT,
    analysis_revision INTEGER,
    action TEXT NOT NULL CHECK(action IN ('accept','modify','reject','manual')),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)),
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id,patient_id) REFERENCES analysis_input_snapshots(id,patient_id),
    FOREIGN KEY(run_id,analysis_revision) REFERENCES analysis_result_versions(run_id,revision),
    UNIQUE(patient_id,version),
    UNIQUE(actor_id,patient_id,request_key),
    CHECK((action='manual' AND run_id IS NULL AND analysis_revision IS NULL)
       OR (action!='manual' AND run_id IS NOT NULL AND analysis_revision IS NOT NULL))
);
CREATE TRIGGER backend_diagnosis_review_scope BEFORE INSERT ON backend_diagnosis_reviews BEGIN
    SELECT CASE WHEN json_extract(new.receipt_json,'$.id') IS NOT new.id
        OR json_extract(new.receipt_json,'$.patient_id') IS NOT new.patient_id
        OR json_extract(new.receipt_json,'$.version') IS NOT new.version
        OR json_extract(new.receipt_json,'$.actor_id') IS NOT new.actor_id
        OR json_extract(new.receipt_json,'$.relationship_id') IS NOT new.relationship_id
        OR json_extract(new.receipt_json,'$.snapshot_id') IS NOT new.snapshot_id
        OR json_extract(new.receipt_json,'$.action') IS NOT new.action
        OR json_extract(new.receipt_json,'$.clinical_release') IS NOT 'blocked'
        OR json_extract(new.receipt_json,'$.clinical_ready') IS NOT 0
        OR json_extract(new.receipt_json,'$.treatment_applied') IS NOT 0
        THEN RAISE(ABORT,'diagnosis receipt identity mismatch') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM care_relationships r JOIN users u ON u.id=r.doctor_id
        JOIN patients p ON p.id=r.patient_id WHERE r.id=new.relationship_id
        AND r.patient_id=new.patient_id AND r.doctor_id=new.actor_id
        AND r.ends_at IS NULL AND r.starts_at<=new.recorded_at
        AND u.role='doctor' AND u.disabled=0 AND p.synthetic=1
    ) THEN RAISE(ABORT,'diagnosis requires current synthetic physician relationship') END;
    SELECT CASE WHEN new.version != COALESCE((SELECT max(version)+1 FROM backend_diagnosis_reviews WHERE patient_id=new.patient_id),1)
        THEN RAISE(ABORT,'diagnosis version conflict') END;
    SELECT CASE WHEN new.previous_id IS NOT (SELECT id FROM backend_diagnosis_reviews WHERE patient_id=new.patient_id ORDER BY version DESC LIMIT 1)
        THEN RAISE(ABORT,'diagnosis parent conflict') END;
    SELECT CASE WHEN new.run_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM analysis_runs r JOIN analysis_result_versions v ON v.run_id=r.id
        WHERE r.id=new.run_id AND r.patient_id=new.patient_id AND r.relationship_id=new.relationship_id
        AND r.snapshot_id=new.snapshot_id AND r.operation='diagnosis'
        AND v.revision=new.analysis_revision AND v.status='ready'
    ) THEN RAISE(ABORT,'diagnosis analysis mismatch') END;
END;
CREATE TRIGGER backend_diagnosis_review_no_update BEFORE UPDATE ON backend_diagnosis_reviews BEGIN SELECT RAISE(ABORT,'retain physician diagnosis'); END;
CREATE TRIGGER backend_diagnosis_review_no_delete BEFORE DELETE ON backend_diagnosis_reviews BEGIN SELECT RAISE(ABORT,'retain physician diagnosis'); END;
