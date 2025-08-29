# backend/routers/diet_router.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from backend.services import diet_service as svc

router = APIRouter()

class IngredientRequest(BaseModel):
    ingredients: List[str]

@router.get("/user-ingredients")
def user_ingredients():
    df = svc.user_df().copy()
    if "group_name" not in df.columns:
        df["group_name"] = "Other"
    df["group_name"] = df["group_name"].fillna("Other")
    return df[["ingredient_name", "group_name"]].to_dict(orient="records")

@router.post("/reload")
def reload_csvs():
    return svc.load_csvs()

@router.post("/calculate")
def calculate(req: IngredientRequest):
    return svc.calculate_diet(req.ingredients)
