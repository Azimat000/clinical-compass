CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TABLE users (
    id TEXT PRIMARY KEY NOT NULL, role TEXT NOT NULL CHECK(role IN ('doctor','patient')),
    display_name TEXT NOT NULL, password_hash TEXT, disabled INTEGER NOT NULL DEFAULT 1 CHECK(disabled IN (0,1))
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY NOT NULL, user_id TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE patients (
    id TEXT PRIMARY KEY NOT NULL, user_id TEXT UNIQUE REFERENCES users(id), code TEXT NOT NULL UNIQUE,
    birth_date TEXT, age_years INTEGER CHECK(age_years >= 0 AND age_years <= 120),
    age_status TEXT NOT NULL CHECK(age_status IN ('known','unknown','conflicting')),
    synthetic INTEGER NOT NULL CHECK(synthetic = 1), created_at TEXT NOT NULL,
    CHECK((age_status = 'known' AND (age_years IS NOT NULL OR birth_date IS NOT NULL)) OR age_status != 'known')
);
CREATE TABLE care_relationships (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    doctor_id TEXT NOT NULL REFERENCES users(id), starts_at TEXT NOT NULL, ends_at TEXT,
    UNIQUE(patient_id, doctor_id, starts_at)
);
CREATE UNIQUE INDEX one_leading_doctor ON care_relationships(patient_id) WHERE ends_at IS NULL;
CREATE TABLE encounters (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id), occurred_at TEXT NOT NULL,
    author_id TEXT REFERENCES users(id), narrative TEXT NOT NULL, origin TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX encounters_timeline ON encounters(patient_id, occurred_at);
CREATE VIRTUAL TABLE encounter_search USING fts5(encounter_id UNINDEXED, narrative, tokenize='unicode61');
CREATE TRIGGER encounter_search_insert AFTER INSERT ON encounters BEGIN
    INSERT INTO encounter_search(encounter_id, narrative) VALUES(new.id, new.narrative);
END;
CREATE TRIGGER encounter_search_update AFTER UPDATE ON encounters BEGIN
    DELETE FROM encounter_search WHERE encounter_id = old.id;
    INSERT INTO encounter_search(encounter_id, narrative) VALUES(new.id, new.narrative);
END;
CREATE TRIGGER encounter_search_delete AFTER DELETE ON encounters BEGIN
    DELETE FROM encounter_search WHERE encounter_id = old.id;
END;
CREATE TABLE observations (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    encounter_id TEXT REFERENCES encounters(id), code TEXT NOT NULL,
    value_json TEXT CHECK(value_json IS NULL OR json_valid(value_json)), unit TEXT,
    data_status TEXT NOT NULL CHECK(data_status IN ('known','unknown','conflicting','denied')),
    observed_at TEXT NOT NULL, recorded_at TEXT NOT NULL, provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
    CHECK(data_status != 'unknown' OR value_json IS NULL)
);
CREATE INDEX observations_timeline ON observations(patient_id, code, observed_at);
CREATE TABLE source_versions (
    id TEXT PRIMARY KEY NOT NULL, source_code TEXT NOT NULL, version TEXT NOT NULL, url TEXT NOT NULL,
    sha256 TEXT NOT NULL, checked_at TEXT NOT NULL, population_json TEXT NOT NULL CHECK(json_valid(population_json)),
    rights_status TEXT NOT NULL CHECK(rights_status IN ('unknown','verified','restricted')),
    validation_status TEXT NOT NULL CHECK(validation_status IN ('unknown','verified','rejected')),
    status TEXT NOT NULL CHECK(status IN ('unverified','current','superseded')), UNIQUE(source_code, version)
);
CREATE TABLE catalog_versions (
    id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('scale','drug','rule','route','alert')),
    code TEXT NOT NULL, version TEXT NOT NULL, source_version_id TEXT NOT NULL REFERENCES source_versions(id),
    definition_json TEXT NOT NULL CHECK(json_valid(definition_json)),
    min_age INTEGER, max_age INTEGER, age_basis TEXT,
    status TEXT NOT NULL DEFAULT 'inactive' CHECK(status IN ('inactive','reviewed','retired')),
    reviewed_by TEXT REFERENCES users(id), reviewed_at TEXT, blocker TEXT,
    CHECK(status != 'reviewed' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND age_basis IS NOT NULL)),
    UNIQUE(kind, code, version)
);
CREATE TABLE assessments (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    scale_version_id TEXT NOT NULL REFERENCES catalog_versions(id), assigned_by TEXT REFERENCES users(id),
    completed_at TEXT, answers_json TEXT NOT NULL CHECK(json_valid(answers_json)), score REAL,
    completeness TEXT NOT NULL CHECK(completeness IN ('complete','incomplete','unknown')),
    scoring_version TEXT NOT NULL, CHECK(completeness = 'complete' OR score IS NULL)
);
CREATE INDEX assessments_timeline ON assessments(patient_id, scale_version_id, completed_at);
CREATE TABLE self_reports (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id), received_at TEXT NOT NULL,
    reported_at TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    idempotency_key TEXT NOT NULL UNIQUE, schema_version INTEGER NOT NULL
);
CREATE TABLE proposals (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    kind TEXT NOT NULL CHECK(kind IN ('therapy_start','therapy_change','therapy_stop','referral','plan_change')),
    version INTEGER NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    input_snapshot_json TEXT NOT NULL CHECK(json_valid(input_snapshot_json)),
    catalog_version_id TEXT REFERENCES catalog_versions(id), created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','withdrawn','review_pending'))
);
CREATE TABLE doctor_confirmations (
    id TEXT PRIMARY KEY NOT NULL, proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals(id),
    doctor_id TEXT NOT NULL REFERENCES users(id), proposal_version INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')), rationale TEXT NOT NULL,
    confirmed_at TEXT NOT NULL, UNIQUE(id, decision)
);
CREATE TABLE care_actions (
    id TEXT PRIMARY KEY NOT NULL, confirmation_id TEXT NOT NULL UNIQUE,
    approval_decision TEXT NOT NULL DEFAULT 'approved' CHECK(approval_decision = 'approved'),
    effective_at TEXT NOT NULL, supersedes_id TEXT REFERENCES care_actions(id),
    FOREIGN KEY(confirmation_id, approval_decision) REFERENCES doctor_confirmations(id, decision)
);
CREATE TRIGGER confirmation_guard BEFORE INSERT ON doctor_confirmations BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM users u JOIN care_relationships r ON r.doctor_id=u.id
        JOIN proposals p ON p.patient_id=r.patient_id
        WHERE u.id=new.doctor_id AND u.role='doctor' AND u.disabled=0
        AND r.ends_at IS NULL AND p.id=new.proposal_id
        AND p.version=new.proposal_version AND p.status!='withdrawn'
    ) THEN RAISE(ABORT, 'confirmation requires current leading doctor and proposal version') END;
END;
CREATE TRIGGER confirmation_no_update BEFORE UPDATE ON doctor_confirmations BEGIN SELECT RAISE(ABORT, 'immutable confirmation'); END;
CREATE TRIGGER confirmation_no_delete BEFORE DELETE ON doctor_confirmations BEGIN SELECT RAISE(ABORT, 'immutable confirmation'); END;
CREATE TRIGGER confirmed_proposal_no_update BEFORE UPDATE ON proposals WHEN EXISTS (
    SELECT 1 FROM doctor_confirmations WHERE proposal_id=old.id
) BEGIN SELECT RAISE(ABORT, 'create a new proposal version'); END;
CREATE TABLE therapy_courses (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    action_id TEXT NOT NULL UNIQUE REFERENCES care_actions(id),
    drug_version_id TEXT NOT NULL REFERENCES catalog_versions(id), schedule_json TEXT NOT NULL CHECK(json_valid(schedule_json)),
    starts_at TEXT NOT NULL, ends_at TEXT, off_label_rationale TEXT
);
CREATE TABLE referrals (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals(id),
    category TEXT CHECK(category IN ('mandatory','desirable')), severity TEXT,
    destination TEXT NOT NULL, action_id TEXT UNIQUE REFERENCES care_actions(id)
);
CREATE TABLE risk_evaluations (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    rule_version_id TEXT NOT NULL REFERENCES catalog_versions(id),
    result TEXT NOT NULL CHECK(result IN ('present','absent','unknown','conflicting')),
    evaluated_at TEXT NOT NULL, evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json))
);
CREATE TABLE adverse_events (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    therapy_id TEXT REFERENCES therapy_courses(id), reported_at TEXT NOT NULL,
    description TEXT NOT NULL, review_status TEXT NOT NULL CHECK(review_status IN ('unreviewed','reviewed'))
);
CREATE TABLE alerts (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    rule_version_id TEXT NOT NULL REFERENCES catalog_versions(id),
    category TEXT NOT NULL CHECK(category IN ('therapy_safety','psychiatry_route','critical')),
    urgency TEXT NOT NULL, created_at TEXT NOT NULL, doctor_seen_at TEXT,
    doctor_response_at TEXT, response_json TEXT CHECK(response_json IS NULL OR json_valid(response_json))
);
CREATE TABLE conversations (
    id TEXT PRIMARY KEY NOT NULL, relationship_id TEXT NOT NULL UNIQUE REFERENCES care_relationships(id)
);
CREATE TABLE messages (
    id TEXT PRIMARY KEY NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id),
    sender_id TEXT NOT NULL REFERENCES users(id), body TEXT NOT NULL, sent_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);
CREATE INDEX messages_timeline ON messages(conversation_id, sent_at);
CREATE TABLE adherence_reports (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    action_id TEXT NOT NULL REFERENCES care_actions(id), planned_at TEXT NOT NULL, reported_at TEXT,
    outcome TEXT NOT NULL CHECK(outcome IN ('taken','missed','unknown','conflicting')), reason TEXT
);
CREATE TABLE documents (
    id TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    format TEXT NOT NULL, sha256 TEXT NOT NULL, storage_key TEXT NOT NULL, origin TEXT NOT NULL,
    received_at TEXT NOT NULL, synthetic INTEGER NOT NULL CHECK(synthetic = 1)
);
CREATE TABLE extraction_runs (
    id TEXT PRIMARY KEY NOT NULL, document_id TEXT NOT NULL REFERENCES documents(id),
    parser_version TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending','complete','failed')), error_code TEXT
);
CREATE TABLE extracted_facts (
    id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES extraction_runs(id), field TEXT NOT NULL,
    value_json TEXT CHECK(value_json IS NULL OR json_valid(value_json)),
    data_status TEXT NOT NULL CHECK(data_status IN ('known','unknown','conflicting','denied')),
    quote TEXT, span_start INTEGER, span_end INTEGER, confidence REAL,
    CHECK(data_status != 'unknown' OR value_json IS NULL)
);
CREATE TABLE consents (
    id TEXT PRIMARY KEY NOT NULL, user_id TEXT NOT NULL REFERENCES users(id), purpose TEXT NOT NULL,
    document_version TEXT NOT NULL, granted_at TEXT NOT NULL, revoked_at TEXT, evidence_ref TEXT NOT NULL
);
CREATE TABLE audit_entries (
    id INTEGER PRIMARY KEY, actor_id TEXT REFERENCES users(id), event TEXT NOT NULL,
    entity_id TEXT NOT NULL, occurred_at TEXT NOT NULL, metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json))
);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_entries BEGIN SELECT RAISE(ABORT, 'append-only audit'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_entries BEGIN SELECT RAISE(ABORT, 'append-only audit'); END;
CREATE TABLE outbox_events (
    id TEXT PRIMARY KEY NOT NULL, topic TEXT NOT NULL, aggregate_id TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processed','dead')),
    attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL, processed_at TEXT, last_error TEXT
);
CREATE INDEX outbox_ready ON outbox_events(status, available_at, created_at);
CREATE TABLE event_receipts (
    event_id TEXT NOT NULL REFERENCES outbox_events(id), consumer TEXT NOT NULL,
    processed_at TEXT NOT NULL, PRIMARY KEY(event_id, consumer)
);
CREATE TABLE deliveries (
    id TEXT PRIMARY KEY NOT NULL, event_id TEXT NOT NULL REFERENCES outbox_events(id),
    recipient_id TEXT NOT NULL REFERENCES users(id), channel TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','delivered','acknowledged','dead')),
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL,
    delivered_at TEXT, acknowledged_at TEXT, last_error TEXT, UNIQUE(event_id, recipient_id, channel)
);
