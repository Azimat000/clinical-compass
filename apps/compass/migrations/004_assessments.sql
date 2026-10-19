-- A verified source may be exercised in synthetic demo without claiming clinical approval.
CREATE TABLE assessment_form_releases (
    form_version_id TEXT PRIMARY KEY NOT NULL REFERENCES catalog_versions(id),
    definition_sha256 TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope='synthetic_demo'),
    released_at TEXT NOT NULL
);
CREATE TABLE assessment_requests (
    id TEXT PRIMARY KEY NOT NULL,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    form_version_id TEXT NOT NULL REFERENCES assessment_form_releases(form_version_id),
    requested_by TEXT NOT NULL REFERENCES users(id),
    requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    age_on TEXT NOT NULL,
    age_years INTEGER NOT NULL CHECK(age_years BETWEEN 18 AND 120),
    age_basis TEXT NOT NULL CHECK(length(trim(age_basis)) > 0),
    age_snapshot_json TEXT NOT NULL CHECK(json_valid(age_snapshot_json)),
    request_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
CREATE INDEX assessment_request_patient ON assessment_requests(patient_id,requested_at);
CREATE TABLE assessment_results (
    assessment_id TEXT PRIMARY KEY NOT NULL REFERENCES assessments(id),
    request_id TEXT NOT NULL UNIQUE REFERENCES assessment_requests(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    observed_on TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    scores_json TEXT CHECK(scores_json IS NULL OR json_valid(scores_json))
);
CREATE TRIGGER assessment_request_author BEFORE INSERT ON assessment_requests BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM care_relationships r JOIN users u ON u.id=r.doctor_id
        JOIN patients p ON p.id=r.patient_id WHERE r.id=new.relationship_id
        AND r.patient_id=new.patient_id AND r.doctor_id=new.requested_by
        AND r.ends_at IS NULL AND r.starts_at<=new.requested_at
        AND u.role='doctor' AND u.disabled=0 AND p.synthetic=1
    ) THEN RAISE(ABORT, 'assessment requires leading doctor') END;
END;
CREATE TRIGGER assessment_result_author BEFORE INSERT ON assessment_results BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM assessment_requests q JOIN care_relationships r ON r.id=q.relationship_id
        JOIN patients p ON p.id=q.patient_id JOIN users u ON u.id=new.actor_id
        JOIN users d ON d.id=r.doctor_id JOIN assessments a ON a.id=new.assessment_id
        WHERE q.id=new.request_id AND r.ends_at IS NULL AND r.starts_at<=new.recorded_at
        AND q.expires_at>new.recorded_at AND u.disabled=0 AND d.disabled=0
        AND p.synthetic=1 AND a.patient_id=q.patient_id AND a.scale_version_id=q.form_version_id
        AND a.assigned_by=q.requested_by AND a.score IS NULL
        AND ((u.role='patient' AND p.user_id=u.id) OR (u.role='doctor' AND r.doctor_id=u.id))
        AND ((a.completeness='complete' AND new.scores_json IS NOT NULL)
          OR (a.completeness='incomplete' AND new.scores_json IS NULL))
    ) THEN RAISE(ABORT, 'assessment requires authorized response') END;
END;
CREATE TRIGGER assessment_request_no_update BEFORE UPDATE ON assessment_requests BEGIN SELECT RAISE(ABORT,'append-only assessment request'); END;
CREATE TRIGGER assessment_request_no_delete BEFORE DELETE ON assessment_requests BEGIN SELECT RAISE(ABORT,'append-only assessment request'); END;
CREATE TRIGGER assessment_result_no_update BEFORE UPDATE ON assessment_results BEGIN SELECT RAISE(ABORT,'append-only assessment result'); END;
CREATE TRIGGER assessment_result_no_delete BEFORE DELETE ON assessment_results BEGIN SELECT RAISE(ABORT,'append-only assessment result'); END;
CREATE TRIGGER completed_assessment_no_update BEFORE UPDATE ON assessments WHEN EXISTS(SELECT 1 FROM assessment_results WHERE assessment_id=old.id) BEGIN SELECT RAISE(ABORT,'append-only assessment'); END;
CREATE TRIGGER completed_assessment_no_delete BEFORE DELETE ON assessments WHEN EXISTS(SELECT 1 FROM assessment_results WHERE assessment_id=old.id) BEGIN SELECT RAISE(ABORT,'append-only assessment'); END;
CREATE TRIGGER released_definition_no_rewrite BEFORE UPDATE ON catalog_versions
WHEN EXISTS(SELECT 1 FROM assessment_form_releases WHERE form_version_id=old.id)
AND (new.id IS NOT old.id OR new.kind IS NOT old.kind OR new.code IS NOT old.code
 OR new.version IS NOT old.version OR new.source_version_id IS NOT old.source_version_id
 OR new.definition_json IS NOT old.definition_json OR new.min_age IS NOT old.min_age
 OR new.max_age IS NOT old.max_age OR new.age_basis IS NOT old.age_basis)
BEGIN SELECT RAISE(ABORT,'released form requires new version'); END;
CREATE TRIGGER released_source_no_rewrite BEFORE UPDATE ON source_versions
WHEN EXISTS(SELECT 1 FROM catalog_versions c JOIN assessment_form_releases r ON r.form_version_id=c.id WHERE c.source_version_id=old.id)
AND (new.id IS NOT old.id OR new.url IS NOT old.url OR new.sha256 IS NOT old.sha256 OR new.version IS NOT old.version
 OR new.population_json IS NOT old.population_json)
BEGIN SELECT RAISE(ABORT,'released source requires new version'); END;
CREATE TRIGGER assessment_release_no_update BEFORE UPDATE ON assessment_form_releases BEGIN SELECT RAISE(ABORT,'immutable assessment release'); END;
CREATE TRIGGER assessment_release_no_delete BEFORE DELETE ON assessment_form_releases BEGIN SELECT RAISE(ABORT,'immutable assessment release'); END;
