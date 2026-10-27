-- Separate factual medication reconciliation. Never a diagnosis or prescription.
CREATE TABLE backend_therapy_contexts (
 id TEXT PRIMARY KEY NOT NULL,
 patient_id TEXT NOT NULL REFERENCES patients(id),
 relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
 actor_id TEXT NOT NULL REFERENCES users(id),
 version INTEGER NOT NULL CHECK(version>0),
 previous_id TEXT REFERENCES backend_therapy_contexts(id),
 request_key TEXT NOT NULL,
 base_sha256 TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 recorded_at TEXT NOT NULL,
 UNIQUE(patient_id,version), UNIQUE(actor_id,patient_id,request_key)
);
CREATE TRIGGER therapy_context_scope BEFORE INSERT ON backend_therapy_contexts BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM care_relationships r JOIN users u ON u.id=r.doctor_id
 JOIN patients p ON p.id=r.patient_id WHERE r.id=new.relationship_id AND r.patient_id=new.patient_id
 AND r.doctor_id=new.actor_id AND r.ends_at IS NULL AND r.starts_at<=new.recorded_at
 AND u.role='doctor' AND u.disabled=0 AND p.synthetic=1)
 THEN RAISE(ABORT,'synthetic physician relationship required') END;
 SELECT CASE WHEN new.version != COALESCE((SELECT max(version)+1 FROM backend_therapy_contexts WHERE patient_id=new.patient_id),1)
 OR new.previous_id IS NOT (SELECT id FROM backend_therapy_contexts WHERE patient_id=new.patient_id ORDER BY version DESC LIMIT 1)
 THEN RAISE(ABORT,'therapy context version conflict') END;
 SELECT CASE WHEN json_extract(new.payload_json,'$.reviewed') IS NOT 1
 OR json_extract(new.payload_json,'$.version') IS NOT 'therapy-context-v1'
 THEN RAISE(ABORT,'explicit factual reconciliation required') END;
END;
CREATE TRIGGER therapy_context_no_update BEFORE UPDATE ON backend_therapy_contexts BEGIN SELECT RAISE(ABORT,'retain therapy context'); END;
CREATE TRIGGER therapy_context_no_delete BEFORE DELETE ON backend_therapy_contexts BEGIN SELECT RAISE(ABORT,'retain therapy context'); END;
