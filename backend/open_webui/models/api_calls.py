import time
import uuid
from typing import Optional

from sqlalchemy import BigInteger, Column, Integer, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.internal.db import Base, get_async_db_context


class APICall(Base):
    __tablename__ = 'api_call'

    id = Column(Text, primary_key=True)
    method = Column(Text, nullable=False, index=True)
    path = Column(Text, nullable=False, index=True)
    status_code = Column(Integer, nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    created_at = Column(BigInteger, nullable=False, index=True)


class APICalls:
    @staticmethod
    async def record(
        method: str,
        path: str,
        status_code: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        db: Optional[AsyncSession] = None,
    ) -> None:
        async with get_async_db_context(db) as db:
            db.add(
                APICall(
                    id=str(uuid.uuid4()),
                    method=method,
                    path=path,
                    status_code=status_code,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    created_at=int(time.time()),
                )
            )
            await db.commit()

    @staticmethod
    async def summary(start_date: int | None = None, end_date: int | None = None, db=None) -> dict:
        async with get_async_db_context(db) as db:
            stmt = select(
                func.count(APICall.id),
                func.coalesce(func.sum(APICall.input_tokens), 0),
                func.coalesce(func.sum(APICall.output_tokens), 0),
            )
            if start_date is not None:
                stmt = stmt.where(APICall.created_at >= start_date)
            if end_date is not None:
                stmt = stmt.where(APICall.created_at <= end_date)
            count, input_tokens, output_tokens = (await db.execute(stmt)).one()
            return {
                'total_calls': count,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
            }
