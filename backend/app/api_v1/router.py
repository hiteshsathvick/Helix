import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SchemaProbe
from app.core.deps import get_db

router = APIRouter(prefix="/api/v1")


class ProbeCreate(BaseModel):
    message: str


class ProbeRead(BaseModel):
    id: uuid.UUID
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/probes", response_model=ProbeRead, status_code=201)
async def create_probe(body: ProbeCreate, db: AsyncSession = Depends(get_db)) -> SchemaProbe:
    probe = SchemaProbe(message=body.message)
    db.add(probe)
    await db.commit()
    await db.refresh(probe)
    return probe


@router.get("/probes", response_model=list[ProbeRead])
async def list_probes(db: AsyncSession = Depends(get_db)) -> list[SchemaProbe]:
    result = await db.execute(select(SchemaProbe).order_by(SchemaProbe.created_at))
    return list(result.scalars().all())
