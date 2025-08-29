from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers.diet_router import router  # <- import the router object directly

app = FastAPI(title="Dog Diet Planner API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/")
def root():
    return {"message": "Dog Diet Planner API is running"}
