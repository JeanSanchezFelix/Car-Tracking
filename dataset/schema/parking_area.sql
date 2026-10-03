CREATE TABLE parking_area (
    parking_area_id BIGINT PRIMARY KEY,
    name            TEXT,
    capacity        BIGINT,
    geom            geometry(Polygon, 4326),
    created_at      TIMESTAMP
);
