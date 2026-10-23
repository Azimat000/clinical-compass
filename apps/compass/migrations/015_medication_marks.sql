CREATE TABLE medication_marks (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 patient_id TEXT NOT NULL REFERENCES patients(id),
 proposal_id TEXT NOT NULL REFERENCES proposals(id),
 med_index INTEGER NOT NULL CHECK(med_index BETWEEN 0 AND 7),
 slot_index INTEGER NOT NULL CHECK(slot_index BETWEEN 0 AND 3),
 dose_on TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES users(id),
 actual_quarters INTEGER CHECK(actual_quarters BETWEEN 0 AND 80),
 recorded_at TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE
);
CREATE INDEX medication_marks_patient_day ON medication_marks(patient_id,dose_on,sequence);
CREATE TRIGGER medication_mark_no_update BEFORE UPDATE ON medication_marks BEGIN SELECT RAISE(ABORT,'immutable medication mark'); END;
CREATE TRIGGER medication_mark_no_delete BEFORE DELETE ON medication_marks BEGIN SELECT RAISE(ABORT,'immutable medication mark'); END;
