-- Explicit synthetic-only activation. Existing installations remain disabled.
CREATE TABLE backend_job_settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    generation_version TEXT NOT NULL CHECK(length(generation_version)>0)
);
INSERT INTO backend_job_settings VALUES(1,0,'be06-unavailable-v1');
CREATE TABLE backend_jobs (
    run_id TEXT PRIMARY KEY REFERENCES analysis_runs(id),
    state TEXT NOT NULL CHECK(state IN ('pending','running','done','cancelled')),
    lane TEXT NOT NULL CHECK(lane IN ('risk','generation')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
    available_at TEXT NOT NULL,
    lease_until TEXT,
    token TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX backend_jobs_ready ON backend_jobs(lane,state,available_at);
CREATE TABLE backend_job_attempts (
    run_id TEXT NOT NULL REFERENCES backend_jobs(run_id),
    attempt INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL CHECK(outcome IN ('running','retry','done','failed','expired','stale','cancelled')),
    error_code TEXT,
    PRIMARY KEY(run_id,attempt)
);
CREATE TRIGGER backend_job_attempt_no_delete BEFORE DELETE ON backend_job_attempts BEGIN SELECT RAISE(ABORT,'retain job attempts'); END;

CREATE TRIGGER backend_intent_clinical_entries_insert AFTER INSERT ON clinical_entries
WHEN (SELECT enabled FROM backend_job_settings WHERE id=1)=1 BEGIN
    INSERT INTO outbox_events(id,topic,aggregate_id,payload_json,created_at,available_at)
    SELECT lower(hex(randomblob(16))), 'backend.data_changed.v1', new.patient_id,
        json_object('relationship_id',r.id,'doctor_id',r.doctor_id),
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00',
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00'
    FROM care_relationships r JOIN users u ON u.id=r.doctor_id
    WHERE r.patient_id=new.patient_id AND r.ends_at IS NULL AND u.disabled=0;
END;

CREATE TRIGGER backend_intent_first_visit_versions_insert AFTER INSERT ON first_visit_versions
WHEN (SELECT enabled FROM backend_job_settings WHERE id=1)=1 BEGIN
    INSERT INTO outbox_events(id,topic,aggregate_id,payload_json,created_at,available_at)
    SELECT lower(hex(randomblob(16))), 'backend.data_changed.v1', new.patient_id,
        json_object('relationship_id',r.id,'doctor_id',r.doctor_id),
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00',
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00'
    FROM care_relationships r JOIN users u ON u.id=r.doctor_id
    WHERE r.patient_id=new.patient_id AND r.ends_at IS NULL AND u.disabled=0;
END;

CREATE TRIGGER backend_intent_observations_insert AFTER INSERT ON observations
WHEN (SELECT enabled FROM backend_job_settings WHERE id=1)=1 BEGIN
    INSERT INTO outbox_events(id,topic,aggregate_id,payload_json,created_at,available_at)
    SELECT lower(hex(randomblob(16))), 'backend.data_changed.v1', new.patient_id,
        json_object('relationship_id',r.id,'doctor_id',r.doctor_id),
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00',
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00'
    FROM care_relationships r JOIN users u ON u.id=r.doctor_id
    WHERE r.patient_id=new.patient_id AND r.ends_at IS NULL AND u.disabled=0;
END;

CREATE TRIGGER backend_intent_observations_update AFTER UPDATE ON observations
WHEN (SELECT enabled FROM backend_job_settings WHERE id=1)=1 BEGIN
    INSERT INTO outbox_events(id,topic,aggregate_id,payload_json,created_at,available_at)
    SELECT lower(hex(randomblob(16))), 'backend.data_changed.v1', new.patient_id,
        json_object('relationship_id',r.id,'doctor_id',r.doctor_id),
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00',
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00'
    FROM care_relationships r JOIN users u ON u.id=r.doctor_id
    WHERE r.patient_id=new.patient_id AND r.ends_at IS NULL AND u.disabled=0;
END;

CREATE TRIGGER backend_intent_assessment_results_insert AFTER INSERT ON assessment_results
WHEN (SELECT enabled FROM backend_job_settings WHERE id=1)=1 BEGIN
    INSERT INTO outbox_events(id,topic,aggregate_id,payload_json,created_at,available_at)
    SELECT lower(hex(randomblob(16))), 'backend.data_changed.v1', (SELECT patient_id FROM assessments WHERE id=new.assessment_id),
        json_object('relationship_id',r.id,'doctor_id',r.doctor_id),
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00',
        strftime('%Y-%m-%dT%H:%M:%f','now') || '000+00:00'
    FROM care_relationships r JOIN users u ON u.id=r.doctor_id
    WHERE r.patient_id=(SELECT patient_id FROM assessments WHERE id=new.assessment_id) AND r.ends_at IS NULL AND u.disabled=0;
END;
