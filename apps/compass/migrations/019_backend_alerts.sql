-- Physician-only synthetic review alerts. Transport uses the existing outbox.
CREATE TABLE backend_alerts (
    id TEXT PRIMARY KEY NOT NULL,
    episode_id TEXT NOT NULL,
    episode_revision INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE REFERENCES outbox_events(id),
    relationship_id TEXT NOT NULL REFERENCES care_relationships(id),
    recipient_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    queued_at TEXT NOT NULL,
    FOREIGN KEY(episode_id,episode_revision) REFERENCES backend_risk_episode_versions(episode_id,revision),
    UNIQUE(episode_id,episode_revision)
);
CREATE TABLE backend_alert_actions (
    sequence INTEGER PRIMARY KEY,
    alert_id TEXT NOT NULL REFERENCES backend_alerts(id),
    action TEXT NOT NULL CHECK(action IN ('received','seen','processed')),
    actor_id TEXT NOT NULL REFERENCES users(id),
    reason TEXT NOT NULL,
    request_key TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    UNIQUE(alert_id,action)
);
CREATE INDEX backend_alerts_recipient ON backend_alerts(recipient_id,queued_at,id);
CREATE TRIGGER backend_alert_scope BEFORE INSERT ON backend_alerts BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM backend_risk_episodes e JOIN backend_risk_episode_versions v ON v.episode_id=e.id
        JOIN care_relationships r ON r.id=e.relationship_id JOIN outbox_events o ON o.id=new.event_id
        JOIN patients p ON p.id=e.patient_id
        WHERE e.id=new.episode_id AND v.revision=new.episode_revision AND v.state='open'
        AND e.relationship_id=new.relationship_id AND r.doctor_id=new.recipient_id AND p.synthetic=1
        AND o.topic='backend.risk_alert.v1' AND o.aggregate_id=new.id
    ) THEN RAISE(ABORT,'invalid backend alert scope') END;
END;
CREATE TRIGGER backend_alert_action_scope BEFORE INSERT ON backend_alert_actions BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM backend_alerts a JOIN care_relationships r ON r.id=a.relationship_id
        JOIN users u ON u.id=r.doctor_id JOIN deliveries d ON d.event_id=a.event_id
        WHERE a.id=new.alert_id AND a.recipient_id=new.actor_id AND r.doctor_id=new.actor_id
        AND r.ends_at IS NULL AND r.starts_at<=new.recorded_at AND u.disabled=0 AND u.role='doctor'
        AND d.recipient_id=new.actor_id AND d.channel='physician_api_v1' AND d.status='delivered'
    ) THEN RAISE(ABORT,'alert requires authorized delivered physician channel') END;
    SELECT CASE WHEN new.action='seen' AND NOT EXISTS (
        SELECT 1 FROM backend_alert_actions WHERE alert_id=new.alert_id AND action='received'
    ) THEN RAISE(ABORT,'receipt required') END;
    SELECT CASE WHEN new.action='processed' AND (length(trim(new.reason))=0 OR NOT EXISTS (
        SELECT 1 FROM backend_alert_actions WHERE alert_id=new.alert_id AND action='seen'
    )) THEN RAISE(ABORT,'view and reason required') END;
    SELECT CASE WHEN new.action='processed' AND NOT EXISTS (
        SELECT 1 FROM backend_alerts a JOIN backend_risk_episode_versions v ON v.episode_id=a.episode_id
        WHERE a.id=new.alert_id AND v.revision=a.episode_revision+1 AND v.state='closed'
        AND v.request_key=new.request_key AND v.actor_id=new.actor_id AND v.reason=new.reason
    ) THEN RAISE(ABORT,'exact physician episode closure required') END;
END;
CREATE TRIGGER backend_alerts_no_update BEFORE UPDATE ON backend_alerts BEGIN SELECT RAISE(ABORT,'retain alert'); END;
CREATE TRIGGER backend_alerts_no_delete BEFORE DELETE ON backend_alerts BEGIN SELECT RAISE(ABORT,'retain alert'); END;
CREATE TRIGGER backend_alert_actions_no_update BEFORE UPDATE ON backend_alert_actions BEGIN SELECT RAISE(ABORT,'retain alert action'); END;
CREATE TRIGGER backend_alert_actions_no_delete BEFORE DELETE ON backend_alert_actions BEGIN SELECT RAISE(ABORT,'retain alert action'); END;
