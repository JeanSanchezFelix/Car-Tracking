CREATE TABLE trip (
    trip_id     BIGINT PRIMARY KEY,
    vehicle_id  BIGINT REFERENCES vehicle (vehicle_id),
    start_ts    TIMESTAMP,
    end_ts      TIMESTAMP,
    start_geom  geometry(Point, 4326),
    end_geom    geometry(Point, 4326),
    distance_km DOUBLE PRECISION
);
