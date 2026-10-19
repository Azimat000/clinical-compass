-- Additive search projection; old clinical entries and versions remain unchanged.
CREATE VIRTUAL TABLE clinical_entry_search USING fts5(entry_id UNINDEXED, body, tokenize='unicode61');
INSERT INTO clinical_entry_search(entry_id,body) SELECT id,summary || ' ' || payload_json FROM clinical_entries;
CREATE TRIGGER clinical_entry_search_insert AFTER INSERT ON clinical_entries BEGIN
    INSERT INTO clinical_entry_search(entry_id,body) VALUES(new.id,new.summary || ' ' || new.payload_json);
END;
CREATE VIRTUAL TABLE import_search USING fts5(import_id UNINDEXED, body, tokenize='unicode61');
INSERT INTO import_search(import_id,body) SELECT id,source_text FROM text_imports;
CREATE TRIGGER import_search_insert AFTER INSERT ON text_imports BEGIN
    INSERT INTO import_search(import_id,body) VALUES(new.id,new.source_text);
END;
CREATE INDEX patients_age_code ON patients(age_status,code);
CREATE INDEX relationship_doctor_patients ON care_relationships(doctor_id,ends_at,patient_id,starts_at);
CREATE INDEX entry_patient_kind ON clinical_entries(patient_id,kind,observed_on);
CREATE INDEX proposal_patient_kind ON proposals(patient_id,kind,created_at);

CREATE VIRTUAL TABLE patient_search USING fts5(patient_id UNINDEXED, label, tokenize='unicode61');
INSERT INTO patient_search(patient_id,label) SELECT id,id || ' ' || code FROM patients;
CREATE TRIGGER patient_search_insert AFTER INSERT ON patients BEGIN
    INSERT INTO patient_search(patient_id,label) VALUES(new.id,new.id || ' ' || new.code);
END;
CREATE TRIGGER patient_search_update AFTER UPDATE OF code,id ON patients BEGIN
    DELETE FROM patient_search WHERE patient_id=old.id;
    INSERT INTO patient_search(patient_id,label) VALUES(new.id,new.id || ' ' || new.code);
END;
CREATE TRIGGER patient_search_delete AFTER DELETE ON patients BEGIN
    DELETE FROM patient_search WHERE patient_id=old.id;
END;
