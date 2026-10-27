-- Private checkpoints, not clinical conclusions. No default activation.
CREATE TABLE analysis_packet_results (
    run_id TEXT NOT NULL REFERENCES analysis_runs(id),
    operation TEXT NOT NULL CHECK(operation IN ('risk','diagnosis')),
    branch TEXT NOT NULL,
    packet_index INTEGER NOT NULL CHECK(packet_index>0),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    runtime_sha256 TEXT NOT NULL CHECK(length(runtime_sha256)=64),
    response_json TEXT NOT NULL CHECK(json_valid(response_json)),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(run_id,operation,branch,packet_index,payload_sha256,runtime_sha256)
);
CREATE TRIGGER analysis_packet_no_update BEFORE UPDATE ON analysis_packet_results BEGIN SELECT RAISE(ABORT,'immutable packet response'); END;
CREATE TRIGGER analysis_packet_no_delete BEFORE DELETE ON analysis_packet_results BEGIN SELECT RAISE(ABORT,'retain packet response'); END;
