from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Car-Tracking API")

origins = ['*']

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Phase II endpoints TODO  ---
BASE_PATH = "/api/v1"


@app.get("/")
async def root():
    return {"message": "Car-Tracking API is running", "base_path": BASE_PATH}
