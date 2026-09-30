import json
import re
import time
import uuid

from open_webui.models.api_calls import APICalls
from open_webui.models.config import Config

_collection_cache_version = 0


def invalidate_collection_cache() -> None:
    global _collection_cache_version
    _collection_cache_version += 1


async def record_async_model_usage(request, model_id: str | None, usage: dict | None, user_id: str | None) -> None:
    """Attach a saved chat's completed model usage to its originating API request."""
    call_id = getattr(request.state, 'api_call_analytics_id', None)
    if not call_id or not getattr(request.state, 'api_call_analytics_async', False):
        return
    input_tokens, output_tokens = APICallAnalyticsMiddleware._usage_counts(usage or {})
    try:
        await APICalls.record_model_usage(
            api_call_id=call_id,
            model_id=model_id,
            user_id=user_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            created_at=getattr(request.state, 'api_call_analytics_created_at', int(time.time())),
        )
    except Exception:
        # Analytics must not interrupt a completed chat response.
        pass


class APICallAnalyticsMiddleware:
    """Collect request metadata and provider usage while the admin switch is on."""

    CONFIG_KEY = 'analytics.api_call_collection'
    CACHE_SECONDS = 1
    MAX_CAPTURE_BYTES = 2_000_000
    MODEL_PATH = re.compile(r'/(?:chat/completions|completions|responses|messages|embeddings|embed|generate|chat)(?:/\d+)?$')

    def __init__(self, app):
        self.app = app
        self._enabled = False
        self._checked_at = 0.0
        self._cache_version = -1

    async def _is_enabled(self) -> bool:
        now = time.monotonic()
        if self._cache_version != _collection_cache_version or now - self._checked_at >= self.CACHE_SECONDS:
            try:
                self._enabled = bool(await Config.get(self.CONFIG_KEY, False))
            except Exception:
                self._enabled = False
            self._checked_at = now
            self._cache_version = _collection_cache_version
        return self._enabled

    @staticmethod
    def _read_usage(body: bytearray) -> tuple[int, int]:
        if not body:
            return 0, 0
        try:
            text = body.decode('utf-8', errors='ignore')
            try:
                payloads = [json.loads(text)]
            except (ValueError, TypeError):
                # Streaming endpoints commonly return one JSON object per line.
                payloads = []
                for line in text.splitlines():
                    line = line.removeprefix('data:').strip()
                    if not line or line == '[DONE]':
                        continue
                    try:
                        payloads.append(json.loads(line))
                    except (ValueError, TypeError):
                        continue
        except ValueError:
            return 0, 0

        usages = []

        def walk(value):
            if isinstance(value, dict):
                usage = value.get('usage')
                if isinstance(usage, dict):
                    usages.append(usage)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for payload in payloads:
            walk(payload)
        token_keys = {
            'input_tokens', 'prompt_tokens', 'prompt_eval_count', 'prompt_n', 'cache_n',
            'output_tokens', 'completion_tokens', 'eval_count', 'predicted_n',
        }
        for usage in reversed(usages):
            if any(key in usage for key in token_keys):
                return APICallAnalyticsMiddleware._usage_counts(usage)
        return 0, 0

    @staticmethod
    def _usage_counts(usage: dict) -> tuple[int, int]:
        try:
            input_tokens = next(
                (usage[key] for key in ('input_tokens', 'prompt_tokens', 'prompt_eval_count') if usage.get(key) is not None),
                None,
            )
            if input_tokens is None:
                input_tokens = int(usage.get('prompt_n') or 0) + int(usage.get('cache_n') or 0)
            output_tokens = next(
                (usage[key] for key in ('output_tokens', 'completion_tokens', 'eval_count', 'predicted_n') if usage.get(key) is not None),
                0,
            )
            return max(0, int(input_tokens)), max(0, int(output_tokens))
        except (TypeError, ValueError):
            return 0, 0

    @staticmethod
    def _read_model(body: bytearray) -> str | None:
        if not body:
            return None

        def model_from_payload(payload) -> str | None:
            if isinstance(payload, dict):
                model = payload.get('model')
                if isinstance(model, str) and model.strip():
                    return model.strip()[:512]
            return None

        text = body.decode('utf-8', errors='ignore')
        try:
            return model_from_payload(json.loads(text))
        except (ValueError, TypeError):
            for line in text.splitlines():
                if not line.startswith('data:'):
                    continue
                try:
                    model = model_from_payload(json.loads(line.removeprefix('data:').strip()))
                except (ValueError, TypeError):
                    continue
                if model:
                    return model
        return None

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if (
            scope['type'] != 'http'
            or not path.startswith('/api/')
            or path.startswith('/api/v1/analytics/')
            or not await self._is_enabled()
        ):
            return await self.app(scope, receive, send)

        response_body = bytearray()
        request_body = bytearray()
        call_id = str(uuid.uuid4())
        created_at = int(time.time())
        state = scope.setdefault('state', {})
        state['api_call_analytics_id'] = call_id
        state['api_call_analytics_created_at'] = created_at
        capture_model = scope.get('method') == 'POST' and bool(self.MODEL_PATH.search(path))
        request_too_large = False
        status_code = 500

        async def receive_capture():
            nonlocal request_too_large
            message = await receive()
            if message['type'] == 'http.request' and not request_too_large:
                chunk = message.get('body', b'')
                if len(request_body) + len(chunk) <= self.MAX_CAPTURE_BYTES:
                    request_body.extend(chunk)
                else:
                    request_body.clear()
                    request_too_large = True
            return message

        async def send_capture(message):
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message['status']
            elif message['type'] == 'http.response.body':
                response_body.extend(message.get('body', b''))
                if len(response_body) > self.MAX_CAPTURE_BYTES:
                    del response_body[: len(response_body) - self.MAX_CAPTURE_BYTES]
            await send(message)

        try:
            await self.app(scope, receive_capture if capture_model else receive, send_capture)
        finally:
            input_tokens, output_tokens = self._read_usage(response_body)
            model_id = (
                self._read_model(request_body) or self._read_model(response_body)
                if capture_model else None
            )
            authenticated_user = (scope.get('state') or {}).get('user')
            try:
                await APICalls.record(
                    method=scope['method'],
                    path=getattr(scope.get('route'), 'path', None) or 'unmatched',
                    status_code=status_code,
                    user_id=getattr(authenticated_user, 'id', None),
                    model_id=model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    call_id=call_id,
                    created_at=created_at,
                )
            except Exception:
                # Collection should never interfere with API responses.
                pass
