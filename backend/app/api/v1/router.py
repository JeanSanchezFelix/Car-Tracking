from fastapi import APIRouter

from backend.app.api.v1.handlers import drivers, parking_areas, road_segments, vehicle_assignments, vehicles

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(vehicles.router)
api_router.include_router(drivers.router)
api_router.include_router(vehicle_assignments.router)