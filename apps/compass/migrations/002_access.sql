ALTER TABLE sessions ADD COLUMN csrf_token TEXT;
ALTER TABLE sessions ADD COLUMN last_seen_at TEXT;
CREATE TABLE login_challenges (
    token_hash TEXT PRIMARY KEY NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE login_limits (
    subject_hash TEXT PRIMARY KEY NOT NULL, attempts INTEGER NOT NULL, window_end TEXT NOT NULL
);
CREATE TABLE care_invitations (
    token_hash TEXT PRIMARY KEY NOT NULL, patient_id TEXT NOT NULL REFERENCES patients(id),
    doctor_id TEXT NOT NULL REFERENCES users(id), recipient_user_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL, consumed_at TEXT, revoked_at TEXT
);
CREATE TABLE relationship_checks (
    id TEXT PRIMARY KEY NOT NULL, relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    patient_user_id TEXT NOT NULL REFERENCES users(id), received_at TEXT NOT NULL
);
CREATE TRIGGER relationship_roles BEFORE INSERT ON care_relationships BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM users WHERE id=new.doctor_id AND role='doctor' AND disabled=0
    ) THEN RAISE(ABORT, 'active doctor required') END;
END;
CREATE TRIGGER patient_user_role BEFORE UPDATE OF user_id ON patients WHEN new.user_id IS NOT NULL BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM users WHERE id=new.user_id AND role='patient' AND disabled=0
    ) THEN RAISE(ABORT, 'active patient required') END;
END;
CREATE TRIGGER relationship_check_guard BEFORE INSERT ON relationship_checks BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM care_relationships r JOIN patients p ON p.id=r.patient_id
        JOIN users u ON u.id=p.user_id
        WHERE r.id=new.relationship_id AND r.ends_at IS NULL
        AND p.user_id=new.patient_user_id AND u.disabled=0
    ) THEN RAISE(ABORT, 'current patient relationship required') END;
END;
