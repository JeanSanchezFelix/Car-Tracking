CREATE TABLE vehicle_type (
    vehicle_type_id  BIGINT PRIMARY KEY,
    vehicle_kind_id  BIGINT REFERENCES vehicle_kind (vehicle_kind_id),
    fuel_type_id     BIGINT REFERENCES fuel_type (fuel_type_id),
    emissions_rating DOUBLE PRECISION,
    created_at       TIMESTAMP
);
