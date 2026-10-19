-- A synthetic manual decision workflow; no clinical rule release is created.
CREATE TABLE decision_drafts (
    proposal_id TEXT PRIMARY KEY REFERENCES proposals(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    request_key TEXT NOT NULL UNIQUE,
    parent_proposal_id TEXT REFERENCES proposals(id),
    reference_json TEXT NOT NULL CHECK(json_valid(reference_json))
);
CREATE TRIGGER decision_draft_no_update BEFORE UPDATE ON decision_drafts BEGIN SELECT RAISE(ABORT, 'immutable decision metadata'); END;
CREATE TRIGGER decision_draft_no_delete BEFORE DELETE ON decision_drafts BEGIN SELECT RAISE(ABORT, 'immutable decision metadata'); END;
CREATE TRIGGER decision_proposal_no_update BEFORE UPDATE ON proposals WHEN EXISTS (
    SELECT 1 FROM decision_drafts WHERE proposal_id=old.id
) BEGIN SELECT RAISE(ABORT, 'create a new decision version'); END;
CREATE TRIGGER decision_proposal_no_delete BEFORE DELETE ON proposals WHEN EXISTS (
    SELECT 1 FROM decision_drafts WHERE proposal_id=old.id
) BEGIN SELECT RAISE(ABORT, 'immutable decision proposal'); END;
CREATE TRIGGER care_action_no_update BEFORE UPDATE ON care_actions BEGIN SELECT RAISE(ABORT, 'immutable care action'); END;
CREATE TRIGGER care_action_no_delete BEFORE DELETE ON care_actions BEGIN SELECT RAISE(ABORT, 'immutable care action'); END;
