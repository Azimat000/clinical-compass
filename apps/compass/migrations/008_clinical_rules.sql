CREATE TABLE clinical_contexts (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    observed_on TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    request_key TEXT NOT NULL UNIQUE
);
CREATE INDEX clinical_contexts_patient ON clinical_contexts(patient_id);
CREATE TRIGGER clinical_context_author BEFORE INSERT ON clinical_contexts BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM users u JOIN care_relationships r ON r.doctor_id=u.id JOIN patients p ON p.id=r.patient_id
        WHERE u.id=new.actor_id AND u.role='doctor' AND u.disabled=0 AND p.synthetic=1
        AND p.id=new.patient_id AND r.id=new.relationship_id AND r.ends_at IS NULL AND r.starts_at<=new.recorded_at
    ) THEN RAISE(ABORT, 'context requires authorized synthetic doctor') END;
END;
CREATE TABLE clinical_rule_evaluations (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    entry_id TEXT NOT NULL UNIQUE REFERENCES clinical_entries(id),
    context_id TEXT REFERENCES clinical_contexts(id),
    rule_version TEXT NOT NULL CHECK(rule_version='A02-v2'),
    result TEXT NOT NULL CHECK(result IN ('triggered','no_match','unknown','conflicting','not_applicable')),
    recorded_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json))
);
CREATE INDEX clinical_rule_evaluations_patient ON clinical_rule_evaluations(patient_id);
CREATE TRIGGER clinical_rule_evaluation_patient BEFORE INSERT ON clinical_rule_evaluations BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM clinical_entries e WHERE e.id=new.entry_id
        AND e.patient_id=new.patient_id AND e.kind='self_report') OR (new.context_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM clinical_contexts c WHERE c.id=new.context_id AND c.patient_id=new.patient_id))
    THEN RAISE(ABORT, 'evaluation source mismatch') END;
END;
CREATE TABLE critical_events (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    evaluation_id TEXT NOT NULL UNIQUE REFERENCES clinical_rule_evaluations(id),
    rule_version TEXT NOT NULL CHECK(rule_version='A02-v2'),
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
    relationship_id TEXT REFERENCES care_relationships(id),
    recipient_id TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    delivery_state TEXT NOT NULL CHECK(delivery_state IN ('pending_s10','unassigned')),
    outbox_event_id TEXT NOT NULL UNIQUE REFERENCES outbox_events(id),
    CHECK((delivery_state='unassigned' AND relationship_id IS NULL AND recipient_id IS NULL)
       OR (delivery_state='pending_s10' AND relationship_id IS NOT NULL AND recipient_id IS NOT NULL))
);
CREATE INDEX critical_events_patient ON critical_events(patient_id);
CREATE TRIGGER critical_event_source BEFORE INSERT ON critical_events BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM clinical_rule_evaluations e WHERE e.id=new.evaluation_id
        AND e.patient_id=new.patient_id AND e.rule_version=new.rule_version AND e.result='triggered')
        OR (new.relationship_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM care_relationships r
        WHERE r.id=new.relationship_id AND r.patient_id=new.patient_id AND r.doctor_id=new.recipient_id))
    THEN RAISE(ABORT, 'critical event source mismatch') END;
END;
CREATE TRIGGER clinical_contexts_no_update BEFORE UPDATE ON clinical_contexts BEGIN SELECT RAISE(ABORT, 'immutable clinical context'); END;
CREATE TRIGGER clinical_contexts_no_delete BEFORE DELETE ON clinical_contexts BEGIN SELECT RAISE(ABORT, 'immutable clinical context'); END;
CREATE TRIGGER clinical_rule_evaluations_no_update BEFORE UPDATE ON clinical_rule_evaluations BEGIN SELECT RAISE(ABORT, 'immutable clinical evaluation'); END;
CREATE TRIGGER clinical_rule_evaluations_no_delete BEFORE DELETE ON clinical_rule_evaluations BEGIN SELECT RAISE(ABORT, 'immutable clinical evaluation'); END;
CREATE TRIGGER critical_events_no_update BEFORE UPDATE ON critical_events BEGIN SELECT RAISE(ABORT, 'immutable critical event'); END;
CREATE TRIGGER critical_events_no_delete BEFORE DELETE ON critical_events BEGIN SELECT RAISE(ABORT, 'immutable critical event'); END;
