"""
Sherlock - Customer Ratings Router
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.db.models import Store, CustomerRating

router = APIRouter(prefix="/ratings", tags=["Ratings"])


class RatingSubmit(BaseModel):
    shop: str
    rating: int  # 1-5
    comment: Optional[str] = None


@router.post("/submit")
async def submit_rating(
    data: RatingSubmit,
    db: AsyncSession = Depends(get_db)
):
    """Submit a customer rating"""
    
    # Validate rating
    if data.rating < 1 or data.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    
    # Find store
    result = await db.execute(
        select(Store).where(Store.shopify_domain == data.shop)
    )
    store = result.scalar()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Create rating
    rating = CustomerRating(
        store_id=store.id,
        rating=data.rating,
        comment=data.comment
    )
    
    db.add(rating)
    await db.commit()
    
    return {"success": True, "message": "Thank you for your feedback!"}