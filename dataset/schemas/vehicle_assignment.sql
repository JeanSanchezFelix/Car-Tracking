CREATE TABLE vehicle_assignment (
    assignment_id BIGINT PRIMARY KEY,
    vehicle_id    BIGINT REFERENCES vehicle (vehicle_id),
    driver_id     BIGINT REFERENCES driver (driver_id),
    assigned_from TIMESTAMP,
    assigned_to   TIMESTAMP
);
