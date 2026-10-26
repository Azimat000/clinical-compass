-- Internal synthetic analyses; clinical actions stay in the existing decision workflow.
CREATE TABLE analysis_input_snapshots (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    created_at TEXT NOT NULL,
    UNIQUE(id,patient_id)
);
CREATE TABLE analysis_runs (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    snapshot_id TEXT NOT NULL,
    actor_id TEXT NOT NULL REFERENCES users(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    operation TEXT NOT NULL CHECK(operation IN ('risk','diagnosis','plan')),
    request_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id,patient_id) REFERENCES analysis_input_snapshots(id,patient_id),
    UNIQUE(actor_id,patient_id,request_key)
);
CREATE INDEX analysis_runs_patient ON analysis_runs(patient_id,created_at,id);
CREATE TABLE analysis_result_versions (
    run_id TEXT NOT NULL REFERENCES analysis_runs(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    status TEXT NOT NULL CHECK(status IN ('queued','running','ready','insufficient_data','unsupported','stale','failed')),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)
        AND json_type(payload_json,'$.release.status')='text'
        AND json_extract(payload_json,'$.release.status')='blocked'
        AND json_extract(payload_json,'$.status')=status
        AND json_extract(payload_json,'$.revision')=revision
        AND json_extract(payload_json,'$.run_id')=run_id
        AND json_type(payload_json,'$.revision')='integer'
        AND json_type(payload_json,'$.status')='text'
        AND json_type(payload_json,'$.run_id')='text'
        AND json_type(payload_json,'$.release.status') IS NOT NULL
        AND json_type(payload_json,'$.revision') IS NOT NULL
        AND json_type(payload_json,'$.status') IS NOT NULL
        AND json_type(payload_json,'$.run_id') IS NOT NULL),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(run_id,revision)
);
CREATE TRIGGER analysis_run_author BEFORE INSERT ON analysis_runs BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM care_relationships r JOIN users u ON u.id=r.doctor_id
        JOIN patients p ON p.id=r.patient_id WHERE r.id=new.relationship_id
        AND r.patient_id=new.patient_id AND r.doctor_id=new.actor_id
        AND r.ends_at IS NULL AND r.starts_at<=new.created_at
        AND u.role='doctor' AND u.disabled=0 AND p.synthetic=1
    ) THEN RAISE(ABORT,'analysis requires authorized physician and synthetic case') END;
END;
CREATE TRIGGER analysis_version_sequence BEFORE INSERT ON analysis_result_versions BEGIN
    SELECT CASE WHEN new.revision != COALESCE((SELECT max(revision)+1 FROM analysis_result_versions WHERE run_id=new.run_id),1)
        THEN RAISE(ABORT,'analysis version conflict') END;
    SELECT CASE WHEN new.revision=1 AND new.status!='queued'
        THEN RAISE(ABORT,'analysis starts queued') END;
    SELECT CASE WHEN new.revision>1 AND NOT EXISTS (
        SELECT 1 FROM analysis_result_versions p WHERE p.run_id=new.run_id AND p.revision=new.revision-1 AND (
            (p.status='queued' AND new.status IN ('running','insufficient_data','unsupported','failed','stale')) OR
            (p.status='running' AND new.status IN ('ready','insufficient_data','unsupported','failed','stale')) OR
            (p.status IN ('ready','insufficient_data','unsupported','failed') AND new.status='stale')
        )) THEN RAISE(ABORT,'invalid analysis transition') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM analysis_runs r WHERE r.id=new.run_id
        AND r.patient_id=json_extract(new.payload_json,'$.patient_id')
        AND r.snapshot_id=json_extract(new.payload_json,'$.snapshot_id')
        AND r.operation=json_extract(new.payload_json,'$.operation')
    ) THEN RAISE(ABORT,'analysis identity mismatch') END;
END;
CREATE TRIGGER analysis_snapshot_no_update BEFORE UPDATE ON analysis_input_snapshots BEGIN SELECT RAISE(ABORT,'immutable analysis snapshot'); END;
CREATE TRIGGER analysis_snapshot_no_delete BEFORE DELETE ON analysis_input_snapshots BEGIN SELECT RAISE(ABORT,'immutable analysis snapshot'); END;
CREATE TRIGGER analysis_run_no_update BEFORE UPDATE ON analysis_runs BEGIN SELECT RAISE(ABORT,'immutable analysis run'); END;
CREATE TRIGGER analysis_run_no_delete BEFORE DELETE ON analysis_runs BEGIN SELECT RAISE(ABORT,'immutable analysis run'); END;
CREATE TRIGGER analysis_result_no_update BEFORE UPDATE ON analysis_result_versions BEGIN SELECT RAISE(ABORT,'immutable analysis result'); END;
CREATE TRIGGER analysis_result_no_delete BEFORE DELETE ON analysis_result_versions BEGIN SELECT RAISE(ABORT,'immutable analysis result'); END;
