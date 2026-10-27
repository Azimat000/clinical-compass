-- Provenance only: the existing proposals/confirmations/actions remain authoritative.
CREATE TABLE backend_plan_reviews (
 proposal_id TEXT PRIMARY KEY NOT NULL REFERENCES decision_drafts(proposal_id),
 patient_id TEXT NOT NULL REFERENCES patients(id),
 relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
 actor_id TEXT NOT NULL REFERENCES users(id),
 version INTEGER NOT NULL CHECK(version>0),
 run_id TEXT NOT NULL REFERENCES analysis_runs(id),
 analysis_revision INTEGER NOT NULL,
 request_key TEXT NOT NULL,
 request_json TEXT NOT NULL CHECK(json_valid(request_json)),
 runtime_sha256 TEXT NOT NULL,
 recorded_at TEXT NOT NULL,
 UNIQUE(patient_id,version), UNIQUE(actor_id,patient_id,request_key)
);
CREATE TRIGGER plan_review_scope BEFORE INSERT ON backend_plan_reviews BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM proposals p JOIN decision_drafts d ON d.proposal_id=p.id
 JOIN analysis_runs a ON a.id=new.run_id WHERE p.id=new.proposal_id AND p.patient_id=new.patient_id
 AND a.patient_id=p.patient_id AND a.relationship_id=new.relationship_id AND a.operation='plan'
 AND d.actor_id=new.actor_id AND d.relationship_id=new.relationship_id)
 THEN RAISE(ABORT,'plan provenance mismatch') END;
END;
CREATE TRIGGER plan_review_no_update BEFORE UPDATE ON backend_plan_reviews BEGIN SELECT RAISE(ABORT,'retain plan review'); END;
CREATE TRIGGER plan_review_no_delete BEFORE DELETE ON backend_plan_reviews BEGIN SELECT RAISE(ABORT,'retain plan review'); END;
