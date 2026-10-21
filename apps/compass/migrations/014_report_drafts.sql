-- Mutable private work, deliberately separate from append-only clinical sources.
CREATE TABLE self_report_drafts (
    owner_id TEXT NOT NULL REFERENCES users(id),
    patient_id TEXT NOT NULL REFERENCES patients(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    form_version INTEGER NOT NULL CHECK(form_version=1),
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    request_key TEXT NOT NULL CHECK(length(request_key)=32),
    values_json TEXT NOT NULL CHECK(json_valid(values_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(owner_id,patient_id),
    CHECK(active=1 OR values_json='{}')
);
CREATE TRIGGER report_draft_insert_owner BEFORE INSERT ON self_report_drafts BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM patients p JOIN users u ON u.id=p.user_id
        WHERE p.id=new.patient_id AND u.id=new.owner_id AND u.role='patient'
        AND u.disabled=0 AND p.synthetic=1
    ) THEN RAISE(ABORT,'private draft requires owner') END;
END;
CREATE TRIGGER report_draft_update_owner BEFORE UPDATE ON self_report_drafts BEGIN
    SELECT CASE WHEN new.owner_id!=old.owner_id OR new.patient_id!=old.patient_id
        OR new.revision!=old.revision+1 OR NOT EXISTS (
            SELECT 1 FROM patients p JOIN users u ON u.id=p.user_id
            WHERE p.id=new.patient_id AND u.id=new.owner_id AND u.role='patient'
            AND u.disabled=0 AND p.synthetic=1
        ) THEN RAISE(ABORT,'invalid private draft update') END;
END;
