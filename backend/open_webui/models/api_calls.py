import math
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from open_webui.internal.db import Base, get_async_db_context
from sqlalchemy import BigInteger, Column, Integer, Text, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession


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


class APICallModelUsage(Base):
    __tablename__ = 'api_call_model_usage'

    id = Column(Text, primary_key=True)
    api_call_id = Column(Text, nullable=False, index=True)
    model_id = Column(Text, nullable=True, index=True)
    user_id = Column(Text, nullable=True, index=True)
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
        call_id: str | None = None,
        created_at: int | None = None,
        db: Optional[AsyncSession] = None,
    ) -> None:
        async with get_async_db_context(db) as db:
            db.add(
                APICall(
                    id=call_id or str(uuid.uuid4()),
                    method=method,
                    path=path,
                    user_id=user_id,
                    model_id=model_id,
                    status_code=status_code,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    created_at=created_at if created_at is not None else int(time.time()),
                )
            )
            await db.commit()

    @staticmethod
    async def record_model_usage(
        api_call_id: str,
        model_id: str | None,
        user_id: str | None,
        input_tokens: int,
        output_tokens: int,
        created_at: int,
        db: Optional[AsyncSession] = None,
    ) -> None:
        async with get_async_db_context(db) as db:
            db.add(
                APICallModelUsage(
                    id=str(uuid.uuid4()),
                    api_call_id=api_call_id,
                    model_id=model_id,
                    user_id=user_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    created_at=created_at,
                )
            )
            await db.commit()

    @staticmethod
    def _filter(
        stmt,
        start_date: int | None,
        end_date: int | None,
        group_id: str | None,
        source=APICall,
    ):
        if start_date is not None:
            stmt = stmt.where(source.created_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(source.created_at <= end_date)
        if group_id:
            from open_webui.models.groups import GroupMember

            group_users = select(GroupMember.user_id).where(GroupMember.group_id == group_id)
            stmt = stmt.where(source.user_id.in_(group_users))
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
            usage_stmt = select(
                func.coalesce(func.sum(APICallModelUsage.input_tokens), 0),
                func.coalesce(func.sum(APICallModelUsage.output_tokens), 0),
            )
            usage_input, usage_output = (
                await db.execute(APICalls._filter(usage_stmt, start_date, end_date, group_id, APICallModelUsage))
            ).one()
            input_tokens += usage_input
            output_tokens += usage_output
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
        user_order_by: str = 'count',
        user_direction: str = 'desc',
        db: Optional[AsyncSession] = None,
    ) -> dict:
        from open_webui.models.users import Users

        try:
            tz = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo('UTC')

        async with get_async_db_context(db) as db:
            # Bound implicit all-time ranges before loading grouped timeline rows.
            extrema = []
            for source in (APICall, APICallModelUsage):
                statement = select(func.min(source.created_at), func.max(source.created_at))
                row = (await db.execute(APICalls._filter(statement, start_date, end_date, group_id, source))).one()
                extrema.extend(value for value in row if value is not None)
            first_ts = start_date if start_date is not None else min(extrema) if extrema else None
            last_ts = end_date if end_date is not None else max(extrema) if extrema else None
            bucket_seconds = 60
            if first_ts is not None and last_ts is not None:
                width = 3600 if granularity == 'hourly' else 86400
                if first_ts > last_ts or (last_ts - first_ts) // width + 2 > 10000:
                    raise ValueError('Select a shorter date range (maximum 10000 buckets)')
                # Modern zone offsets divide the aggregation width. Sample each UTC day
                # to include both seasonal offsets; retain minute precision for historical zones.
                if first_ts >= 946684800:
                    bucket_seconds = width
                    for timestamp in range(first_ts, last_ts + 86400, 86400):
                        offset = int(datetime.fromtimestamp(timestamp, tz).utcoffset().total_seconds())
                        bucket_seconds = math.gcd(bucket_seconds, abs(offset))
                    bucket_seconds = math.gcd(bucket_seconds, 3600) if timezone != 'UTC' else bucket_seconds

            summary = await APICalls.summary(start_date, end_date, group_id, db)

            has_model_usage = select(APICallModelUsage.id).where(APICallModelUsage.api_call_id == APICall.id).exists()
            minute = cast(func.floor(APICall.created_at / float(bucket_seconds)), BigInteger).label('minute')
            minute_stmt = (
                select(
                    minute,
                    APICall.model_id,
                    func.count(APICall.id).label('count'),
                    func.coalesce(func.sum(APICall.input_tokens + APICall.output_tokens), 0).label('tokens'),
                )
                .where(~has_model_usage)
                .group_by(minute, APICall.model_id)
                .order_by(minute)
            )
            minute_rows = (await db.execute(APICalls._filter(minute_stmt, start_date, end_date, group_id))).all()
            usage_minute = cast(func.floor(APICallModelUsage.created_at / float(bucket_seconds)), BigInteger).label(
                'minute'
            )
            usage_minute_stmt = (
                select(
                    usage_minute,
                    APICallModelUsage.model_id,
                    func.count(APICallModelUsage.id).label('count'),
                    func.coalesce(func.sum(APICallModelUsage.input_tokens + APICallModelUsage.output_tokens), 0).label(
                        'tokens'
                    ),
                )
                .group_by(usage_minute, APICallModelUsage.model_id)
                .order_by(usage_minute)
            )
            usage_minute_rows = (
                await db.execute(APICalls._filter(usage_minute_stmt, start_date, end_date, group_id, APICallModelUsage))
            ).all()

            counts: dict[str, dict[str, int]] = {}
            token_counts: dict[str, dict[str, int]] = {}
            for row in [*minute_rows, *usage_minute_rows]:
                timestamp = int(row.minute) * bucket_seconds
                dt = datetime.fromtimestamp(timestamp, tz)
                key = (
                    dt.replace(minute=0).isoformat(timespec='minutes')
                    if granularity == 'hourly'
                    else dt.strftime('%Y-%m-%d')
                )
                model_id = row.model_id or 'Unattributed'
                if model_id is not None:
                    bucket = counts.setdefault(key, {})
                    bucket[model_id] = bucket.get(model_id, 0) + int(row.count)
                    token_bucket = token_counts.setdefault(key, {})
                    token_bucket[model_id] = token_bucket.get(model_id, 0) + int(row.tokens)

            timeline = []
            observed_minutes = [int(row.minute) for row in [*minute_rows, *usage_minute_rows]]
            if granularity == 'hourly':
                first_ts = (
                    start_date
                    if start_date is not None
                    else min(observed_minutes) * bucket_seconds
                    if observed_minutes
                    else None
                )
                last_ts = (
                    end_date
                    if end_date is not None
                    else max(observed_minutes) * bucket_seconds
                    if observed_minutes
                    else None
                )
                if first_ts is not None and last_ts is not None:
                    first = int(datetime.fromtimestamp(first_ts, tz).replace(minute=0, second=0).timestamp())
                    last = int(datetime.fromtimestamp(last_ts, tz).replace(minute=0, second=0).timestamp())
                    # Iterate in UTC to retain both offset-separated hours at DST fallback.
                    if (last - first) // 3600 + 1 > 10000:
                        raise ValueError('Select a shorter date range (maximum 10000 hourly buckets)')
                    for timestamp in range(first, last + 1, 3600):
                        key = datetime.fromtimestamp(timestamp, tz).replace(minute=0).isoformat(timespec='minutes')
                        timeline.append(
                            {'date': key, 'models': counts.get(key, {}), 'token_models': token_counts.get(key, {})}
                        )
            else:
                first = (
                    datetime.fromtimestamp(start_date, tz).date()
                    if start_date is not None
                    else (
                        datetime.fromtimestamp(min(observed_minutes) * bucket_seconds, tz).date()
                        if observed_minutes
                        else None
                    )
                )
                last = (
                    datetime.fromtimestamp(end_date, tz).date()
                    if end_date is not None
                    else (
                        datetime.fromtimestamp(max(observed_minutes) * bucket_seconds, tz).date()
                        if observed_minutes
                        else None
                    )
                )
                if first is not None and last is not None:
                    if (last - first).days + 1 > 10000:
                        raise ValueError('Select a shorter date range (maximum 10000 daily buckets)')
                    day = first
                    while day <= last:
                        key = day.isoformat()
                        timeline.append(
                            {'date': key, 'models': counts.get(key, {}), 'token_models': token_counts.get(key, {})}
                        )
                        day += timedelta(days=1)

            model_stmt = (
                select(
                    APICall.model_id,
                    func.count(APICall.id).label('count'),
                    func.coalesce(func.sum(APICall.input_tokens), 0).label('input_tokens'),
                    func.coalesce(func.sum(APICall.output_tokens), 0).label('output_tokens'),
                )
                .where(~has_model_usage)
                .group_by(APICall.model_id)
                .order_by(func.count(APICall.id).desc(), APICall.model_id)
            )
            model_rows = (await db.execute(APICalls._filter(model_stmt, start_date, end_date, group_id))).all()
            usage_model_stmt = select(
                APICallModelUsage.model_id,
                func.count(APICallModelUsage.id).label('count'),
                func.coalesce(func.sum(APICallModelUsage.input_tokens), 0).label('input_tokens'),
                func.coalesce(func.sum(APICallModelUsage.output_tokens), 0).label('output_tokens'),
            ).group_by(APICallModelUsage.model_id)
            usage_model_rows = (
                await db.execute(APICalls._filter(usage_model_stmt, start_date, end_date, group_id, APICallModelUsage))
            ).all()
            model_totals: dict[str | None, dict] = {}
            for row in [*model_rows, *usage_model_rows]:
                model = model_totals.setdefault(
                    row.model_id,
                    {'model_id': row.model_id, 'count': 0, 'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0},
                )
                model['count'] += int(row.count)
                model['input_tokens'] += int(row.input_tokens)
                model['output_tokens'] += int(row.output_tokens)
                model['total_tokens'] += int(row.input_tokens + row.output_tokens)
            models = sorted(model_totals.values(), key=lambda model: (-model['count'], model['model_id'] or ''))

            user_stmt = (
                select(
                    APICall.user_id,
                    func.count(APICall.id).label('count'),
                    func.coalesce(func.sum(APICall.input_tokens), 0).label('input_tokens'),
                    func.coalesce(func.sum(APICall.output_tokens), 0).label('output_tokens'),
                )
                .group_by(APICall.user_id)
                .order_by(func.count(APICall.id).desc())
            )
            user_rows = (await db.execute(APICalls._filter(user_stmt, start_date, end_date, group_id))).all()
            usage_user_stmt = select(
                APICallModelUsage.user_id,
                func.coalesce(func.sum(APICallModelUsage.input_tokens), 0).label('input_tokens'),
                func.coalesce(func.sum(APICallModelUsage.output_tokens), 0).label('output_tokens'),
            ).group_by(APICallModelUsage.user_id)
            usage_user_rows = (
                await db.execute(APICalls._filter(usage_user_stmt, start_date, end_date, group_id, APICallModelUsage))
            ).all()
            usage_by_user = {row.user_id: row for row in usage_user_rows}
            known_ids = [row.user_id for row in user_rows if row.user_id]
            user_info = {u.id: u for u in await Users.get_users_by_user_ids(known_ids, db=db)} if known_ids else {}
            users = [
                {
                    'user_id': row.user_id,
                    'name': user_info[row.user_id].name if row.user_id in user_info else None,
                    'email': user_info[row.user_id].email if row.user_id in user_info else None,
                    'count': int(row.count),
                    'input_tokens': int(
                        row.input_tokens
                        + (usage_by_user[row.user_id].input_tokens if row.user_id in usage_by_user else 0)
                    ),
                    'output_tokens': int(
                        row.output_tokens
                        + (usage_by_user[row.user_id].output_tokens if row.user_id in usage_by_user else 0)
                    ),
                    'total_tokens': int(
                        row.input_tokens
                        + row.output_tokens
                        + (
                            usage_by_user[row.user_id].input_tokens + usage_by_user[row.user_id].output_tokens
                            if row.user_id in usage_by_user
                            else 0
                        )
                    ),
                }
                for row in user_rows
            ]

            users.sort(key=lambda row: row['user_id'] or '')
            users.sort(
                key=lambda row: (row['name'] or '').casefold() if user_order_by == 'name' else row[user_order_by],
                reverse=user_direction == 'desc',
            )
            return {'summary': summary, 'timeline': timeline, 'models': models, 'users': users[:50]}
