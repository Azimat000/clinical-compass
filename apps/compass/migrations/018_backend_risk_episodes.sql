-- Internal synthetic ledger. No delivery, clinical confirmation or care action.
CREATE TABLE backend_risk_episodes (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    origin TEXT NOT NULL CHECK(origin IN ('rule','model_candidate')),
    topic TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(id,relationship_id,origin,topic)
);
CREATE TABLE backend_risk_episode_versions (
    episode_id TEXT NOT NULL REFERENCES backend_risk_episodes(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    state TEXT NOT NULL CHECK(state IN ('open','closed')),
    reason TEXT NOT NULL CHECK(length(trim(reason))>0),
    actor_id TEXT NOT NULL REFERENCES users(id),
    run_id TEXT REFERENCES analysis_runs(id),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    request_key TEXT UNIQUE,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(episode_id,revision)
);
CREATE TABLE backend_risk_episode_evidence (
    episode_id TEXT NOT NULL,
    relationship_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    topic TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES analysis_runs(id),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    FOREIGN KEY(episode_id,relationship_id,origin,topic)
        REFERENCES backend_risk_episodes(id,relationship_id,origin,topic),
    PRIMARY KEY(relationship_id,origin,topic,evidence_sha256)
);
CREATE TABLE backend_risk_episode_evaluations (
    run_id TEXT PRIMARY KEY NOT NULL REFERENCES analysis_runs(id),
    report_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    recorded_at TEXT NOT NULL
);
CREATE INDEX backend_risk_episodes_scope ON backend_risk_episodes(relationship_id,origin,topic);
CREATE TRIGGER backend_risk_episode_scope BEFORE INSERT ON backend_risk_episodes BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM backend_risk_episodes e WHERE e.relationship_id=new.relationship_id
        AND e.origin=new.origin AND e.topic=new.topic AND NOT EXISTS (
            SELECT 1 FROM backend_risk_episode_versions v WHERE v.episode_id=e.id AND v.state='closed')
    ) THEN RAISE(ABORT,'open episode already exists') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM care_relationships r JOIN patients p ON p.id=r.patient_id
        JOIN users u ON u.id=r.doctor_id
        WHERE r.id=new.relationship_id AND r.patient_id=new.patient_id
        AND r.ends_at IS NULL AND r.starts_at<=new.created_at
        AND u.role='doctor' AND u.disabled=0 AND p.synthetic=1
    ) THEN RAISE(ABORT,'episode requires current synthetic physician scope') END;
END;
CREATE TRIGGER backend_risk_episode_sequence BEFORE INSERT ON backend_risk_episode_versions BEGIN
    SELECT CASE WHEN new.revision!=COALESCE((SELECT max(revision)+1 FROM backend_risk_episode_versions WHERE episode_id=new.episode_id),1)
        THEN RAISE(ABORT,'episode revision conflict') END;
    SELECT CASE WHEN new.revision=1 AND (new.state!='open' OR new.run_id IS NULL)
        THEN RAISE(ABORT,'episode starts with observation') END;
    SELECT CASE WHEN EXISTS(SELECT 1 FROM backend_risk_episode_versions WHERE episode_id=new.episode_id AND state='closed')
        THEN RAISE(ABORT,'closed episode is immutable') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM backend_risk_episodes e JOIN care_relationships r ON r.id=e.relationship_id
        JOIN users u ON u.id=r.doctor_id JOIN patients p ON p.id=e.patient_id
        WHERE e.id=new.episode_id AND r.doctor_id=new.actor_id AND r.ends_at IS NULL
        AND r.starts_at<=new.recorded_at AND u.role='doctor' AND u.disabled=0 AND p.synthetic=1
    ) THEN RAISE(ABORT,'episode requires current physician') END;
    SELECT CASE WHEN (new.state='closed' AND (new.run_id IS NOT NULL OR new.request_key IS NULL))
        OR (new.state='open' AND (new.run_id IS NULL OR new.request_key IS NOT NULL))
        THEN RAISE(ABORT,'episode event kind mismatch') END;
    SELECT CASE WHEN new.run_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM analysis_runs a JOIN backend_risk_episodes e ON e.id=new.episode_id
        WHERE a.id=new.run_id AND a.operation='risk' AND a.patient_id=e.patient_id
        AND a.relationship_id=e.relationship_id AND a.actor_id=new.actor_id
    ) THEN RAISE(ABORT,'episode run scope mismatch') END;
END;
CREATE TRIGGER backend_risk_evidence_scope BEFORE INSERT ON backend_risk_episode_evidence BEGIN
    SELECT CASE WHEN EXISTS(SELECT 1 FROM backend_risk_episode_versions WHERE episode_id=new.episode_id AND state='closed')
        THEN RAISE(ABORT,'closed episode evidence is immutable') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM analysis_runs a JOIN backend_risk_episodes e ON e.id=new.episode_id
        WHERE a.id=new.run_id AND a.operation='risk' AND a.patient_id=e.patient_id
        AND a.relationship_id=e.relationship_id
    ) THEN RAISE(ABORT,'evidence run scope mismatch') END;
END;
CREATE TRIGGER backend_risk_episodes_no_update BEFORE UPDATE ON backend_risk_episodes BEGIN SELECT RAISE(ABORT,'retain episode'); END;
CREATE TRIGGER backend_risk_episodes_no_delete BEFORE DELETE ON backend_risk_episodes BEGIN SELECT RAISE(ABORT,'retain episode'); END;
CREATE TRIGGER backend_risk_episode_versions_no_update BEFORE UPDATE ON backend_risk_episode_versions BEGIN SELECT RAISE(ABORT,'retain episode history'); END;
CREATE TRIGGER backend_risk_episode_versions_no_delete BEFORE DELETE ON backend_risk_episode_versions BEGIN SELECT RAISE(ABORT,'retain episode history'); END;
CREATE TRIGGER backend_risk_episode_evidence_no_update BEFORE UPDATE ON backend_risk_episode_evidence BEGIN SELECT RAISE(ABORT,'retain episode evidence'); END;
CREATE TRIGGER backend_risk_episode_evidence_no_delete BEFORE DELETE ON backend_risk_episode_evidence BEGIN SELECT RAISE(ABORT,'retain episode evidence'); END;
CREATE TRIGGER backend_risk_episode_evaluations_no_update BEFORE UPDATE ON backend_risk_episode_evaluations BEGIN SELECT RAISE(ABORT,'retain episode evaluation'); END;
CREATE TRIGGER backend_risk_episode_evaluations_no_delete BEFORE DELETE ON backend_risk_episode_evaluations BEGIN SELECT RAISE(ABORT,'retain episode evaluation'); END;
