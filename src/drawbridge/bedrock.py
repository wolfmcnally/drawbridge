"""Bedrock Converse transports for Drawbridge's text and image stages."""

from __future__ import annotations

import base64
import io
import json
import os
import selectors
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from PIL import Image

from .configuration import child_environment, current_configuration, temporary_directory
from .errors import ConversionOperationalError
from .profile import ProfileError

if TYPE_CHECKING:
    from .profile import Endpoint

REQUEST = "bedrock-converse-request/1"
RESPONSE = "bedrock-converse-response/1"
OUTPUT_LIMIT = 16 * 1024 * 1024
CATEGORIES = {"throttled", "refused", "unavailable", "invalid", "limit"}


class BedrockError(ConversionOperationalError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = dict(items)
    if len(result) != len(items):
        raise BedrockError("invalid")
    return result


def _constant(_value: str) -> None:
    raise BedrockError("invalid")


def _json(raw: bytes) -> dict:
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError) as exc:
        raise BedrockError("invalid") from exc
    if not isinstance(body, dict):
        raise BedrockError("invalid")
    return body


def _exchange(process: subprocess.Popen, request: bytes, deadline: float) -> bytes:
    output = bytearray()
    assert process.stdin is not None and process.stdout is not None
    pending = memoryview(request)
    with selectors.DefaultSelector() as selector:
        for stream, event in ((process.stdin, selectors.EVENT_WRITE), (process.stdout, selectors.EVENT_READ)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, event)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BedrockError("unavailable")
            for key, _ in selector.select(remaining):
                stream = key.fileobj
                try:
                    if stream is process.stdin:
                        pending = pending[os.write(stream.fileno(), pending[:65536]):]
                        if not pending:
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), min(65536, OUTPUT_LIMIT + 1 - len(output)))
                        if not chunk:
                            selector.unregister(stream)
                        output.extend(chunk)
                        if len(output) > OUTPUT_LIMIT:
                            raise BedrockError("limit")
                except BlockingIOError:
                    continue
    if process.wait(timeout=max(0.0, deadline - time.monotonic())) != 0:
        raise BedrockError("unavailable")
    return bytes(output)


def _broker(endpoint: Endpoint, model: str, body: dict) -> dict:
    settings = endpoint.bedrock
    assert settings is not None
    request = json.dumps(
        {"schema": REQUEST, "region": settings.region, "model": model, "body": body},
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    deadline = time.monotonic() + endpoint.timeout_seconds
    with temporary_directory("drawbridge-broker-") as directory:
        work = Path(directory)
        environment = {name: os.environ[name] for name in settings.pass_env if name in os.environ}
        if current_configuration().files:
            environment.update(child_environment(work))
        try:
            for fd in settings.pass_fds:
                os.fstat(fd)
            process = subprocess.Popen(
                endpoint.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=work, env=environment, close_fds=True, pass_fds=settings.pass_fds, start_new_session=True,
            )
        except (OSError, ValueError, NotImplementedError) as exc:
            raise BedrockError("unavailable") from exc
        try:
            response = _json(_exchange(process, request, deadline))
        except (OSError, subprocess.SubprocessError) as exc:
            raise BedrockError("unavailable") from exc
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdin.close()
            process.stdout.close()
    if response.get("schema") != RESPONSE:
        raise BedrockError("invalid")
    if response.get("status") == "ok" and response.keys() == {"schema", "status", "body"}:
        result = response["body"]
        if isinstance(result, dict):
            return result
    if response.get("status") == "error" and response.keys() == {"schema", "status", "category"}:
        category = response["category"]
        if isinstance(category, str) and category in CATEGORIES:
            raise BedrockError(category)
    raise BedrockError("invalid")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _signed_headers(url: str, payload: bytes, region: str) -> dict[str, str]:
    try:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import EnvProvider
        from botocore.exceptions import BotoCoreError
        from botocore.session import get_session
    except ImportError as exc:
        raise BedrockError("unavailable") from exc
    try:
        credentials = EnvProvider().load() if current_configuration().files else get_session().get_credentials()
        if credentials is None:
            raise BedrockError("refused")
        request = AWSRequest(method="POST", url=url, data=payload, headers={"Content-Type": "application/json"})
        SigV4Auth(credentials.get_frozen_credentials(), "bedrock", region).add_auth(request)
        return dict(request.headers)
    except BotoCoreError as exc:
        raise BedrockError("refused") from exc


def _cloud(endpoint: Endpoint, model: str, body: dict) -> dict:
    settings = endpoint.bedrock
    assert settings is not None
    url = f"https://bedrock-runtime.{settings.region}.amazonaws.com/model/{quote(model, safe='')}/converse"
    payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if settings.transport == "sigv4":
        headers = _signed_headers(url, payload, settings.region)
    else:
        try:
            key = endpoint.key()
        except ProfileError:
            raise BedrockError("refused") from None
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=endpoint.timeout_seconds) as response:
            data = response.read(OUTPUT_LIMIT + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        category = (
            "throttled" if exc.code == 429 else "refused" if exc.code in {401, 403}
            else "invalid" if 400 <= exc.code < 500 else "unavailable"
        )
        raise BedrockError(category) from None
    except (OSError, ValueError) as exc:
        raise BedrockError("unavailable") from exc
    if len(data) > OUTPUT_LIMIT:
        raise BedrockError("limit")
    return _json(data)


def _reply(body: dict, token_limit: int) -> tuple[str, int | None, int | None]:
    permitted = {"output", "stopReason", "usage", "metrics", "additionalModelResponseFields",
                 "trace", "performanceConfig", "serviceTier"}
    if body.keys() - permitted:
        raise BedrockError("invalid")
    try:
        envelope = body["output"]
        if envelope.keys() != {"message"}:
            raise BedrockError("invalid")
        message = envelope["message"]
        content = message["content"]
        if (message.keys() != {"role", "content"} or message["role"] != "assistant"
                or not isinstance(content, list) or not content):
            raise BedrockError("invalid")
        if body.get("stopReason") not in {"end_turn", "stop_sequence", "max_tokens"}:
            raise BedrockError("invalid")
        if any(not isinstance(block, dict) or block.keys() != {"text"} or not isinstance(block["text"], str) for block in content):
            raise BedrockError("invalid")
        output = "\n".join(block["text"] for block in content)
        usage = body.get("usage", {})
        if not isinstance(usage, dict) or any(
            field in body and not isinstance(body[field], dict)
            for field in ("metrics", "trace", "performanceConfig", "serviceTier")
        ):
            raise BedrockError("invalid")
        counts = tuple(usage.get(key) for key in ("inputTokens", "outputTokens"))
        if any(count is not None and (type(count) is not int or count < 0) for count in counts):
            raise BedrockError("invalid")
        if counts[1] is not None and counts[1] > token_limit:
            raise BedrockError("limit")
        if not output.strip():
            raise BedrockError("invalid")
    except (AttributeError, KeyError, TypeError) as exc:
        raise BedrockError("invalid") from exc
    return output, counts[0], counts[1]


def converse(
    endpoint: Endpoint, model: str, prompt: str, *, system: str | None = None, jpeg: bytes | None = None,
) -> tuple[str, int | None, int | None]:
    settings = endpoint.bedrock
    assert settings is not None
    content = [{"text": prompt}]
    if jpeg is not None:
        if len(jpeg) > settings.max_image_bytes:
            raise BedrockError("limit")
        with Image.open(io.BytesIO(jpeg)) as image:
            if image.format != "JPEG":
                raise BedrockError("invalid")
            if max(image.size) > settings.max_image_side_px:
                raise BedrockError("limit")
        content.append({"image": {"format": "jpeg", "source": {"bytes": base64.b64encode(jpeg).decode("ascii")}}})
    body = {
        "messages": [{"role": "user", "content": content}],
        "inferenceConfig": {"maxTokens": settings.max_output_tokens, "temperature": 0},
    }
    if system is not None:
        body["system"] = [{"text": system}]
    response = _broker(endpoint, model, body) if settings.transport == "command" else _cloud(endpoint, model, body)
    return _reply(response, settings.max_output_tokens)
