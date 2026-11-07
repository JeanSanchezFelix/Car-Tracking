from fastapi import APIRouter

from backend.app.api.v1.handlers import (
    drivers,
    location_pings,
    parking_areas,
    road_segments,
    trips,
    vehicle_assignments,
    vehicles,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(vehicles.router)
api_router.include_router(drivers.router)
api_router.include_router(vehicle_assignments.router)
api_router.include_router(location_pings.router)
api_router.include_router(location_pings.vehicle_pings_router)
api_router.include_router(parking_areas.router)
api_router.include_router(road_segments.router)
api_router.include_router(trips.router)
api_router.include_router(trips.vehicle_trips_router)