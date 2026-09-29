import time
import uuid
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import BigInteger, Column, Integer, Text, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.internal.db import Base, get_async_db_context


class APICall(Base):
    __tablename__ = 'api_call'

    id = Column(Text, primary_key=True)
    method = Column(Text, nullable=False, index=True)
    path = Column(Text, nullable=False, index=True)
    user_id = Column(Text, nullable=True, index=True)
    model_id = Column(Text, nullable=True, index=True)
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
        user_id: str | None = None,
        model_id: str | None = None,
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
                    user_id=user_id,
                    model_id=model_id,
                    status_code=status_code,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    created_at=int(time.time()),
                )
            )
            await db.commit()

    @staticmethod
    def _filter(stmt, start_date: int | None, end_date: int | None, group_id: str | None):
        if start_date is not None:
            stmt = stmt.where(APICall.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(APICall.created_at <= end_date)
        if group_id:
            from open_webui.models.groups import GroupMember

            group_users = select(GroupMember.user_id).where(GroupMember.group_id == group_id)
            stmt = stmt.where(APICall.user_id.in_(group_users))
        return stmt

    @staticmethod
    async def summary(
        start_date: int | None = None,
        end_date: int | None = None,
        group_id: str | None = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        async with get_async_db_context(db) as db:
            stmt = select(
                func.count(APICall.id),
                func.coalesce(func.sum(APICall.input_tokens), 0),
                func.coalesce(func.sum(APICall.output_tokens), 0),
                func.count(distinct(APICall.user_id)),
            )
            count, input_tokens, output_tokens, users = (
                await db.execute(APICalls._filter(stmt, start_date, end_date, group_id))
            ).one()
            return {
                'total_calls': int(count),
                'input_tokens': int(input_tokens),
                'output_tokens': int(output_tokens),
                'total_tokens': int(input_tokens + output_tokens),
                'total_users': int(users),
            }

    @staticmethod
    async def dashboard(
        start_date: int | None = None,
        end_date: int | None = None,
        group_id: str | None = None,
        granularity: str = 'daily',
        timezone: str = 'UTC',
        db: Optional[AsyncSession] = None,
    ) -> dict:
        from open_webui.models.users import Users

        try:
            tz = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo('UTC')

        async with get_async_db_context(db) as db:
            summary = await APICalls.summary(start_date, end_date, group_id, db)

            minute = cast(func.floor(APICall.created_at / 60.0), BigInteger).label('minute')
            minute_stmt = (
                select(
                    minute,
                    APICall.model_id,
                    func.count(APICall.id).label('count'),
                    func.coalesce(func.sum(APICall.input_tokens + APICall.output_tokens), 0).label('tokens'),
                )
                .group_by(minute, APICall.model_id)
                .order_by(minute)
            )
            minute_rows = (
                await db.execute(APICalls._filter(minute_stmt, start_date, end_date, group_id))
            ).all()

            counts: dict[str, dict[str, int]] = {}
            token_counts: dict[str, dict[str, int]] = {}
            for row in minute_rows:
                timestamp = int(row.minute) * 60
                dt = datetime.fromtimestamp(timestamp, tz)
                key = dt.replace(minute=0).isoformat(timespec='minutes') if granularity == 'hourly' else dt.strftime('%Y-%m-%d')
                model_id = row.model_id or ('Unattributed' if row.tokens else None)
                if model_id is not None:
                    bucket = counts.setdefault(key, {})
                    bucket[model_id] = bucket.get(model_id, 0) + int(row.count)
                    token_bucket = token_counts.setdefault(key, {})
                    token_bucket[model_id] = token_bucket.get(model_id, 0) + int(row.tokens)

            timeline = []
            if granularity == 'hourly':
                first = (start_date // 3600 * 3600) if start_date is not None else (
                    int(minute_rows[0].minute) * 60 // 3600 * 3600 if minute_rows else None
                )
                last = (end_date // 3600 * 3600) if end_date is not None else (
                    int(minute_rows[-1].minute) * 60 // 3600 * 3600 if minute_rows else None
                )
                if first is not None and last is not None:
                    for timestamp in range(first, last + 1, 3600):
                        key = datetime.fromtimestamp(timestamp, tz).isoformat(timespec='minutes')
                        timeline.append({'date': key, 'models': counts.get(key, {}), 'token_models': token_counts.get(key, {})})
            else:
                first = datetime.fromtimestamp(start_date, tz).date() if start_date is not None else (
                    datetime.fromtimestamp(int(minute_rows[0].minute) * 60, tz).date() if minute_rows else None
                )
                last = datetime.fromtimestamp(end_date, tz).date() if end_date is not None else (
                    datetime.fromtimestamp(int(minute_rows[-1].minute) * 60, tz).date() if minute_rows else None
                )
                if first is not None and last is not None:
                    day = first
                    while day <= last:
                        key = day.isoformat()
                        timeline.append({'date': key, 'models': counts.get(key, {}), 'token_models': token_counts.get(key, {})})
                        day += timedelta(days=1)

            model_stmt = (
                select(
                    APICall.model_id,
                    func.count(APICall.id).label('count'),
                    func.coalesce(func.sum(APICall.input_tokens), 0).label('input_tokens'),
                    func.coalesce(func.sum(APICall.output_tokens), 0).label('output_tokens'),
                )
                .where(
                    (APICall.model_id.is_not(None))
                    | (APICall.input_tokens > 0)
                    | (APICall.output_tokens > 0)
                )
                .group_by(APICall.model_id)
                .order_by(func.count(APICall.id).desc(), APICall.model_id)
            )
            model_rows = (await db.execute(APICalls._filter(model_stmt, start_date, end_date, group_id))).all()
            models = [
                {
                    'model_id': row.model_id,
                    'count': int(row.count),
                    'input_tokens': int(row.input_tokens),
                    'output_tokens': int(row.output_tokens),
                    'total_tokens': int(row.input_tokens + row.output_tokens),
                }
                for row in model_rows
            ]

            user_stmt = (
                select(
                    APICall.user_id,
                    func.count(APICall.id).label('count'),
                    func.coalesce(func.sum(APICall.input_tokens), 0).label('input_tokens'),
                    func.coalesce(func.sum(APICall.output_tokens), 0).label('output_tokens'),
                )
                .group_by(APICall.user_id)
                .order_by(func.count(APICall.id).desc())
                .limit(50)
            )
            user_rows = (await db.execute(APICalls._filter(user_stmt, start_date, end_date, group_id))).all()
            known_ids = [row.user_id for row in user_rows if row.user_id]
            user_info = {u.id: u for u in await Users.get_users_by_user_ids(known_ids, db=db)} if known_ids else {}
            users = [
                {
                    'user_id': row.user_id,
                    'name': user_info[row.user_id].name if row.user_id in user_info else None,
                    'email': user_info[row.user_id].email if row.user_id in user_info else None,
                    'count': int(row.count),
                    'input_tokens': int(row.input_tokens),
                    'output_tokens': int(row.output_tokens),
                    'total_tokens': int(row.input_tokens + row.output_tokens),
                }
                for row in user_rows
            ]

            return {'summary': summary, 'timeline': timeline, 'models': models, 'users': users}
