"""
app/api/routes/templates.py
Blueprint template library routes.

GET /templates       — list all starter templates
GET /templates/{id}  — get full template including blueprint_text
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory.database import get_db
from memory.models import ForgeTemplate

router = APIRouter()


class TemplateSummary(BaseModel):
    id: str
    name: str
    category: str
    description: str


class TemplateDetail(BaseModel):
    id: str
    name: str
    category: str
    description: str
    blueprint_text: str


@router.get("", response_model=list[TemplateSummary])
async def list_templates(
    session: AsyncSession = Depends(get_db),
) -> list[TemplateSummary]:
    """List all available blueprint templates."""
    result = await session.execute(
        select(ForgeTemplate).order_by(ForgeTemplate.category, ForgeTemplate.name)
    )
    templates = result.scalars().all()
    return [
        TemplateSummary(
            id=t.id,
            name=t.name,
            category=t.category,
            description=t.description,
        )
        for t in templates
    ]


@router.get("/{template_id}", response_model=TemplateDetail)
async def get_template(
    template_id: str,
    session: AsyncSession = Depends(get_db),
) -> TemplateDetail:
    """Get full template including blueprint_text for pre-filling the submission form."""
    result = await session.execute(
        select(ForgeTemplate).where(ForgeTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return TemplateDetail(
        id=template.id,
        name=template.name,
        category=template.category,
        description=template.description,
        blueprint_text=template.blueprint_text,
    )
