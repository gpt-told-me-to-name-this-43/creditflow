"""Фоновые задачи для выдачи (issue #7)."""

import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Application, ApplicationStatus, ApplicationEvent


async def simulate_disbursement(db: AsyncSession, app_id):
    """Выдача: через несколько секунд после подписания переводит в ISSUED."""
    await asyncio.sleep(3)
    async with db.begin():
        res = await db.execute(
            select(Application).where(Application.id == app_id).with_for_update()
        )
        app = res.scalar_one_or_none()
        if app and app.status == ApplicationStatus.SIGNED.value:
            app.status = ApplicationStatus.ISSUED.value
            app.revision += 1
            app.updated_at = datetime.utcnow()
            db.add(
                ApplicationEvent(
                    application_id=app_id,
                    actor_user_id=None,  # SYSTEM
                    from_status=ApplicationStatus.SIGNED.value,
                    to_status=ApplicationStatus.ISSUED.value,
                )
            )


async def recover_pending_disbursements(db: AsyncSession):
    """Идемпотентная задача: находит SIGNED старше 10 сек и переводит в ISSUED."""
    threshold = datetime.utcnow() - timedelta(seconds=10)
    async with db.begin():
        res = await db.execute(
            select(Application)
            .where(
                Application.status == ApplicationStatus.SIGNED.value,
                Application.updated_at <= threshold,
            )
            .with_for_update(skip_locked=True)
        )
        apps = res.scalars().all()
        for app in apps:
            app.status = ApplicationStatus.ISSUED.value
            app.revision += 1
            app.updated_at = datetime.utcnow()
            db.add(
                ApplicationEvent(
                    application_id=app.id,
                    actor_user_id=None,
                    from_status=ApplicationStatus.SIGNED.value,
                    to_status=ApplicationStatus.ISSUED.value,
                )
            )
