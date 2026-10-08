import asyncio, importlib.util, sys, types, json
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Text, select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(ROOT))
pkg = types.ModuleType('open_webui')
pkg.__path__ = [str(ROOT / 'open_webui')]
sys.modules['open_webui'] = pkg
engine = create_async_engine('sqlite+aiosqlite:///:memory:')
Session = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()


@asynccontextmanager
async def context(db=None):
    if db is not None:
        yield db
    else:
        async with Session() as s:
            yield s


async def dep():
    async with Session() as s:
        yield s


fake = types.ModuleType('open_webui.internal.db')
fake.Base = Base
fake.get_async_db_context = context
fake.get_async_session = dep
sys.modules[fake.__name__] = fake


class Users:
    @staticmethod
    async def get_users_by_user_ids(ids, db=None):
        return [types.SimpleNamespace(id=i, name=i, email=i + '@test.invalid') for i in ids]


fake = types.ModuleType('open_webui.models.users')
fake.Users = Users
sys.modules[fake.__name__] = fake


class GroupMember(Base):
    __tablename__ = 'group_member'
    id = Column(Text, primary_key=True)
    user_id = Column(Text)
    group_id = Column(Text)


fake = types.ModuleType('open_webui.models.groups')
fake.GroupMember = GroupMember
fake.Groups = object
sys.modules[fake.__name__] = fake


class Config:
    @staticmethod
    async def get(*args):
        return True

    @staticmethod
    async def upsert(*args):
        pass


fake = types.ModuleType('open_webui.models.config')
fake.Config = Config
sys.modules[fake.__name__] = fake
from open_webui.models.api_calls import APICall, APICallModelUsage, APICalls
from open_webui.utils.api_call_analytics import APICallAnalyticsMiddleware as MW, record_async_model_usage


async def clear():
    async with Session() as db:
        for t in (APICallModelUsage, APICall, GroupMember):
            await db.execute(delete(t))
        await db.commit()


async def call(path, body, request_body=b'{"model":"m"}', async_usage=None, status=200, method='POST', stream=False):
    async def app(scope, receive, send):
        scope.setdefault('state', {})['user'] = types.SimpleNamespace(id='u')
        scope['route'] = types.SimpleNamespace(path=path)
        await receive()
        if async_usage is not None:
            scope['state']['api_call_analytics_async'] = True
            await record_async_model_usage(Request(scope), 'm', async_usage, 'u')
        await send(
            {
                'type': 'http.response.start',
                'status': status,
                'headers': [(b'content-type', b'text/event-stream' if stream else b'application/json')],
            }
        )
        for start in range(0, len(body), 4096):
            await send(
                {
                    'type': 'http.response.body',
                    'body': body[start : start + 4096],
                    'more_body': start + 4096 < len(body),
                }
            )

    scope = {'type': 'http', 'path': path, 'method': method, 'headers': []}

    async def receive():
        return {'type': 'http.request', 'body': request_body, 'more_body': False}

    async def send(m):
        pass

    await MW(app)(scope, receive, send)
    return await APICalls.dashboard()


# Run this isolated harness directly; infrastructure/auth are stubbed, ORM/router/middleware are real.
import unittest
from open_webui.utils.api_call_analytics import JSONUsageCapture


class AnalyticsRegression(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await clear()

    async def test_generation_reads_and_provider_routes(self):
        history = json.dumps({'chat': {'usage': {'input_tokens': 100, 'output_tokens': 20}}}).encode()
        for _ in range(2):
            result = await call('/api/v1/chats/id', history, method='GET')
        self.assertEqual(result['summary']['total_tokens'], 0)
        self.assertEqual(result['summary']['total_calls'], 2)
        self.assertEqual(result['models'][0]['count'], 2)
        for path in ('/openai/chat/completions', '/openai/responses', '/ollama/api/chat'):
            await clear()
            result = await call(path, b'{"usage":{"input_tokens":10,"output_tokens":4}}')
            self.assertEqual(result['summary']['total_tokens'], 14)
            self.assertEqual(result['summary']['total_calls'], 1)
        await clear()
        result = await call('/ollama/api/chat', b'{"prompt_eval_count":10,"eval_count":4}')
        self.assertEqual(result['summary']['total_tokens'], 14)

    async def test_large_json_and_parser_safety(self):
        body = json.dumps(
            {
                'choices': [{'message': {'content': 'x' * (MW.MAX_CAPTURE_BYTES + 100)}}],
                'usage': {'input_tokens': 100, 'output_tokens': 20},
            }
        ).encode()
        result = await call('/api/chat/completions', body)
        self.assertEqual(result['summary']['total_tokens'], 120)
        self.assertEqual(MW._usage_counts({'input_tokens': float('inf')}), (0, 0))
        await clear()
        result = await call('/api/chat/completions', b'{"usage":{"input_tokens":1e400}}')
        self.assertEqual(result['summary']['total_tokens'], 0)
        # Analytics parsing failures must not escape or replace provider responses.
        result = await call('/api/chat/completions', b'[' * 2000 + b']' * 2000)
        self.assertEqual(result['summary']['total_calls'], 2)

    async def test_stream_partial_and_cumulative_usage(self):
        frames = [
            {'message': {'usage': {'input_tokens': 100, 'output_tokens': 0}}},
            {'usage': {'output_tokens': 20}},
            {'usage': {'output_tokens': 25}},
        ]
        body = b''.join(('data: ' + json.dumps(frame) + '\n\n').encode() for frame in frames)
        result = await call('/api/chat/completions', body, stream=True)
        self.assertEqual(result['summary']['input_tokens'], 100)
        self.assertEqual(result['summary']['output_tokens'], 25)

    async def test_async_fanout_and_no_double_counting(self):
        result = await call(
            '/api/chat/completions',
            b'{"usage":{"input_tokens":10,"output_tokens":4}}',
            async_usage={'input_tokens': 10, 'output_tokens': 4},
        )
        self.assertEqual(result['summary']['total_tokens'], 14)
        await clear()
        await APICalls.record('POST', '/api/chat/completions', 200, 'u', 'm', call_id='fanout', created_at=1760004000)
        for model in ('m', 'n'):
            await APICalls.record_model_usage('fanout', model, 'u', 10, 4, 1760004000)
        result = await APICalls.dashboard()
        self.assertEqual(result['summary']['total_calls'], 1)
        self.assertEqual(sum(row['count'] for row in result['models']), 2)
        self.assertEqual(result['summary']['total_tokens'], 28)

    async def test_timezones_and_dst(self):
        await APICalls.record('POST', '/api/chat/completions', 200, 'u', 'm', 10, 4, created_at=1760004000)
        for zone in ('UTC', 'America/Vancouver', 'Asia/Kolkata', 'Asia/Kathmandu'):
            result = await APICalls.dashboard(
                start_date=1760000400, end_date=1760007600, granularity='hourly', timezone=zone
            )
            self.assertEqual(sum(sum(bucket['token_models'].values()) for bucket in result['timeline']), 14, zone)
        await clear()
        for timestamp in (1762070400, 1762074000):
            await APICalls.record('POST', '/api/chat/completions', 200, 'u', 'm', 10, 4, created_at=timestamp)
        result = await APICalls.dashboard(
            start_date=1762070400, end_date=1762074000, granularity='hourly', timezone='America/Vancouver'
        )
        self.assertEqual(len(result['timeline']), 2)
        self.assertNotEqual(result['timeline'][0]['date'], result['timeline'][1]['date'])

    async def test_top_users_sorted_before_limit_and_group_filter(self):
        for index in range(51):
            for _ in range(2):
                await APICalls.record(
                    'GET', '/api/v1/chats', 200, f'frequent-{index}', None, 1, 1, created_at=1760004000
                )
        await APICalls.record(
            'POST', '/api/chat/completions', 200, 'big-spender', 'm', 1000000, 1, created_at=1760004000
        )
        result = await APICalls.dashboard(user_order_by='input_tokens', user_direction='desc')
        self.assertEqual(len(result['users']), 50)
        self.assertEqual(result['users'][0]['user_id'], 'big-spender')
        async with Session() as db:
            db.add(GroupMember(id='membership', user_id='big-spender', group_id='g'))
            await db.commit()
        result = await APICalls.dashboard(group_id='g')
        self.assertEqual(result['summary']['total_calls'], 1)
        self.assertEqual(result['summary']['total_tokens'], 1000001)

    async def test_real_router_validation_and_collection(self):
        from pydantic import BaseModel

        for name, attrs in [
            ('open_webui.models.chat_messages', {'ChatMessageModel': BaseModel, 'ChatMessages': object}),
            ('open_webui.models.chats', {'Chats': object}),
            ('open_webui.models.feedbacks', {'Feedbacks': object}),
        ]:
            module = types.ModuleType(name)
            module.__dict__.update(attrs)
            sys.modules[name] = module

        async def admin():
            return types.SimpleNamespace(role='admin', id='u')

        module = types.ModuleType('open_webui.utils.auth')
        module.get_admin_user = admin
        sys.modules[module.__name__] = module
        from open_webui.routers.analytics import router
        from fastapi import FastAPI
        import httpx

        app = FastAPI()
        app.include_router(router, prefix='/api/v1/analytics')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for params, status in [
                ({'start_date': 10**19}, 422),
                ({'start_date': 100, 'end_date': 10}, 400),
                ({'start_date': 0, 'end_date': 1000000000, 'granularity': 'hourly'}, 400),
                ({'start_date': 0, 'end_date': 0}, 200),
                ({'user_order_by': 'invalid'}, 422),
            ]:
                response = await client.get('/api/v1/analytics/api-calls/dashboard', params=params)
                self.assertEqual(response.status_code, status, response.text)
            response = await client.get(
                '/api/v1/analytics/api-calls/summary', params={'start_date': 100, 'end_date': 0}
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual((await client.get('/api/v1/analytics/api-calls/collection')).status_code, 200)
            self.assertEqual(
                (await client.post('/api/v1/analytics/api-calls/collection', json={'enabled': False})).status_code, 200
            )


if __name__ == '__main__':
    unittest.main()
