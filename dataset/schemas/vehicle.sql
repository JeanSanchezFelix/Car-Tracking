CREATE TABLE vehicle (
    vehicle_id        BIGINT PRIMARY KEY,
    vehicle_type_id   BIGINT REFERENCES vehicle_type (vehicle_type_id),
    vehicle_status_id BIGINT REFERENCES vehicle_status (vehicle_status_id),
    plate_number      TEXT,
    make              TEXT,
    model             TEXT,
    year              BIGINT,
    created_at        TIMESTAMP
);
