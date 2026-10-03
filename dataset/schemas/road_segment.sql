CREATE TABLE road_segment (
    road_id         BIGINT PRIMARY KEY,
    name            TEXT,
    speed_limit_kph BIGINT,
    geom            geometry(LineString, 4326),
    created_at      TIMESTAMP,
    is_oneway       BOOLEAN,
    direction       TEXT
);
