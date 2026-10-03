CREATE TABLE location_ping (
    ping_id     BIGINT PRIMARY KEY,
    vehicle_id  BIGINT REFERENCES vehicle (vehicle_id),
    ts          TIMESTAMP,
    geom        geometry(Point, 4326),
    speed_kph   DOUBLE PRECISION,
    heading_deg DOUBLE PRECISION
);
