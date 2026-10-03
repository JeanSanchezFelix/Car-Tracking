# Car Tracking

Vehicle tracking system backed by PostgreSQL 17 + PostGIS. This repo covers **Phase I**: the database schema and a Python ETL pipeline that loads the provided Parquet datasets. Later phases add a REST API (FastAPI), a map visualization, and a traffic-statistics dashboard.

## Team

- Luis Jomar Cruz Cruz
- Jean P. I. Sanchez Felix
- Pedro Juan Bonilla Morales

## Tech Stack

- PostgreSQL 17 + PostGIS (Docker)
- Python (ETL), Parquet as input format
- All geometries stored in WGS84 (SRID 4326)
- No ORM, plain SQL only

## Project Structure

```
Car-Tracking/
├── dataset/
│   ├── schema/              # One CREATE TABLE script per table
│   └── *.parquet            # Input data 
└── scripts/
    └── etl_pipeline/
        ├── extract/         # Reads Parquet files
        ├── transform/       # Not needed in Phase I 
        ├── load/            # Inserts data into PostgreSQL
        └── main.py          # Runs the full pipeline
```

## Database Schema

11 tables:

- **Lookup:** `vehicle_kind`, `fuel_type`, `vehicle_status`
- **Fleet:** `vehicle_type`, `vehicle`, `driver`, `vehicle_assignment`
- **Geospatial:** `location_ping` (Point), `trip` (Points), `road_segment` (LineString), `parking_area` (Polygon)

Tables have foreign keys, so scripts must run in this order:

1. `vehicle_kind`, `fuel_type`, `vehicle_status`, `driver`, `parking_area`, `road_segment`
2. `vehicle_type`
3. `vehicle`
4. `vehicle_assignment`, `location_ping`, `trip`

Table Diagram:

```mermaid
classDiagram
direction BT
class driver {
   text first_name
   text last_name
   text license_number
   timestamp hired_at
   bigint driver_id
}
class fuel_type {
   text name
   bigint fuel_type_id
}
class location_ping {
   bigint vehicle_id
   timestamp ts
   Point geom
   double precision speed_kph
   double precision heading_deg
   bigint ping_id
}
class parking_area {
   text name
   bigint capacity
   Polygon geom
   timestamp created_at
   bigint parking_area_id
}
class road_segment {
   text name
   bigint speed_limit_kph
   LineString geom
   timestamp created_at
   boolean is_oneway
   text direction
   bigint road_id
}
class trip {
   bigint vehicle_id
   timestamp start_ts
   timestamp end_ts
   Point start_geom
   Point end_geom
   double precision distance_km
   bigint trip_id
}
class vehicle {
   bigint vehicle_type_id
   bigint vehicle_status_id
   text plate_number
   text make
   text model
   bigint year
   timestamp created_at
   bigint vehicle_id
}
class vehicle_assignment {
   bigint vehicle_id
   bigint driver_id
   timestamp assigned_from
   timestamp assigned_to
   bigint assignment_id
}
class vehicle_kind {
   text name
   bigint vehicle_kind_id
}
class vehicle_status {
   text name
   bigint vehicle_status_id
}
class vehicle_type {
   bigint vehicle_kind_id
   bigint fuel_type_id
   double precision emissions_rating
   timestamp created_at
   bigint vehicle_type_id
}
 
location_ping  -->  vehicle : vehicle_id
trip  -->  vehicle : vehicle_id
vehicle  -->  vehicle_status : vehicle_status_id
vehicle  -->  vehicle_type : vehicle_type_id
vehicle_assignment  -->  driver : driver_id
vehicle_assignment  -->  vehicle : vehicle_id
vehicle_type  -->  fuel_type : fuel_type_id
vehicle_type  -->  vehicle_kind : vehicle_kind_id
```

All geometry columns are stored with SRID 4326 (WGS84).

## Database Credentials (local)

| Setting  | Value                |
| -------- | -------------------- |
| Host     | `localhost`          |
| Port     | `5432`               |
| Database | `jeanpedroli_user`   |
| User     | `jeanpedroli_user`   |
| Password | `<R2oQRxffHEK4l0pncnWjFbEAjIcysj6C>`
| URL     | `postgresql://jeanpedroli_user:R2oQRxffHEK4l0pncnWjFbEAjIcysj6C@dpg-db0k3khsrm7s73furq40-a/jeanpedroli`   |

