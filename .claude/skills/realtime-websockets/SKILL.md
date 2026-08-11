---
name: realtime-websockets
description: Covers pushing live updates to the browser while Django stays WSGI — a separate websocket server, per-user channels, short-lived connection tokens, the subscribe proxy, best-effort publishing, and the polling endpoint that remains the source of truth. Use when adding real-time progress or notifications, working with channels, or debugging why an update did not reach the client.
paths:
  - "**/centrifugo.py"
  - "**/websocket_urls.py"
  - "**/centrifugo/**"
  - "**/progress.py"
---

# Real-Time Updates

Django never holds a websocket. A dedicated websocket server owns the connections; the application
authenticates the user, authorises subscriptions, and pushes events over an HTTP API. The app stays WSGI —
no ASGI server, no long-lived connections in a worker process.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Add a real-time feature | Django stays WSGI — the socket lives in the other service | 1 |
| Name a channel | One channel per **user**, not per job; the prefix must not contain `_` | 2 |
| Authorise a subscription | The proxy is unauthenticated and answers **200** either way | 4 |
| Publish an event | Delivery is best-effort — never let it fail the work that reported it | 5 |
| Design the payload | The polling endpoint must return the identical dict | 6 |
| Report progress in a loop | Every percent is one write and one HTTP call — throttle it | 7 |
| Rely on a client reconnecting | Without history configured, missed messages are gone — resync by polling | 6 |
| Configure it | Two URLs and two secrets, with different audiences — don't mix them up | 8 |

---

## 1. The Architecture

Three participants, and the application is not one of the two holding the socket:

| Step | Who | What |
|---|---|---|
| 1 | Browser → app | authenticates normally, then asks for a connection token |
| 2 | App | returns a short-lived JWT carrying the caller's own id |
| 3 | Browser → websocket server | connects with that token, subscribes to a channel |
| 4 | Websocket server → app | asks the subscribe proxy whether this subscription is allowed |
| 5 | Producer (usually a Celery task) → websocket server | publishes an event over the HTTP API |
| 6 | Websocket server → browser | delivers it |

The app therefore touches real-time in exactly three places: a token endpoint, a subscribe-proxy endpoint,
and a `publish()` helper. Nothing else in the codebase should know the websocket server exists.

---

## 2. Channels Are Per User, Not Per Job

```python
CHANNEL_PREFIXES = frozenset({"reports"})

_CHANNEL_TEMPLATE = "{prefix}_user_{user_id}"


def user_channel(prefix: str, user_id: int) -> str:
    return _CHANNEL_TEMPLATE.format(prefix=prefix, user_id=user_id)
```

❌ **Anti-pattern:** a channel per job (`report_<uuid>`).
**Why?** The browser cannot subscribe until it knows the job id, so every event published in that window is
lost — including a job that fails immediately. A per-user channel is subscribed once, at page load, and
carries every job that user starts. Events are told apart by an id inside the payload.

```python
def parse_user_channel(channel: str) -> int | None:
    """The user id a channel belongs to, or None if the name is not one of ours."""
    parts = channel.split("_")
    if len(parts) != 3:
        return None
    prefix, marker, raw_user_id = parts
    if prefix not in CHANNEL_PREFIXES or marker != "user":
        return None
    try:
        return int(raw_user_id)
    except ValueError:
        return None
```

> ⚠️ **A channel prefix must not contain `_`.** The name is parsed by splitting on it and expecting exactly
> three parts, so a prefix like `test_results` silently stops parsing and every subscription to it is
> refused. Use `testresults` or a hyphen.

Every prefix must be in the whitelist. The whole point of encoding the user id in the name is that
authorisation needs no database query — parse, compare, answer.

---

## 3. The Connection Token

```python
class CentrifugoAuthView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        now = timezone.now()
        payload = {
            "sub": str(request.user.id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=settings.CENTRIFUGO_TOKEN_EXPIRATION_HOURS)).timestamp()),
        }
        token = jwt.encode(payload, key=settings.CENTRIFUGO_TOKEN_HMAC_SECRET_KEY, algorithm="HS256")
        return Response(data={"token": token})
```

The token is signed with the HMAC secret the websocket server shares, and `sub` is taken from
`request.user` — never from a request parameter. A user can only ever connect as themselves.

Keep the expiry short enough that a revoked account loses its connection within a shift. The browser
re-requests a token on reconnect, so a short life costs nothing.

---

## 4. The Subscribe Proxy

The websocket server calls this endpoint over the internal network to ask whether a connection may join a
channel. It is **not** called by a browser.

```python
class CentrifugoSubscribeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    swagger_schema = None

    def post(self, request, *args, **kwargs):
        serializer = CentrifugoSubscribeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(data={"disconnect": {"code": 4000, "reconnect": False, "reason": "Bad Request"}})
        return Response(data={"result": {}})
```

Three things here look wrong and are not:

- **No authentication.** The caller is the websocket server, and the user id in the body came from a JWT it
  already verified. There is no session to authenticate against.
- **Both answers are HTTP 200.** An empty `result` accepts, a `disconnect` block refuses. Returning 403
  reads as a proxy malfunction, not a refusal.
- **Excluded from the schema.** It is not part of the public API.

The validation itself compares the user id parsed from the channel with the one the server reports. That
comparison is the entire authorisation.

> ⚠️ This endpoint must be reachable **only** from the internal network. Exposed publicly, it is an
> unauthenticated endpoint that grants channel access.

---

## 5. Publishing Is Best-Effort

```python
def publish(channel: str, event: str, content: dict) -> bool:
    client = Client(
        api_url=f"{settings.CENTRIFUGO_URL}/api",
        api_key=settings.CENTRIFUGO_API_KEY,
        timeout=settings.CENTRIFUGO_TIMEOUT,
    )
    try:
        client.publish(PublishRequest(channel=channel, data={"event": event, "content": content}))
    except (CentError, RequestException):
        logger.exception("Failed to publish %s to channel %s", event, channel)
        return False
    return True
```

- **Transport failures are logged and swallowed**, never raised. Real-time delivery accelerates the UI; it
  is not the source of truth. A websocket server that is down must not fail the job reporting progress.
- **Set a short timeout** — a second or two. This call sits inside a task doing real work, and a hung HTTP
  request to a sick service is worse than a lost message.
- **Wrap the payload as `{"event": ..., "content": ...}`** so one channel can carry several kinds of update
  and the client dispatches on `event`.
- **Catch the transport exception too.** The client library wraps only some failures into its own error
  type; the underlying request exception still escapes.

> ⚠️ This is one of the few places where catching broadly is correct — but name both exception types
> explicitly rather than reaching for `except Exception`.

---

## 6. The Database Is the Source of Truth

Every real-time update must have a non-real-time equivalent, and they must return **the same payload**.

```python
def report_state(report) -> dict:
    return {
        "uuid": str(report.uuid),
        "status": report.status,
        "progress": report.progress,
        "error": report.error,
        "download_url": download_url(report),
    }
```

The same dict is published to the channel and returned by `GET /reports/<uuid>/`. That is what lets the
front-end handle a websocket message and a poll response with one code path — and what makes a lost
message harmless.

**Write to the database first, publish second.** Publishing a state that was never persisted produces a UI
showing progress the server does not have.

> ⚠️ With no history or recovery configured, a client that reconnects mid-job has missed whatever was
> published while it was away. That is by design — it resyncs through the polling endpoint. Which means the
> polling endpoint is not optional, and it must not be an afterthought that drifts from the channel payload.

When changing either payload, change both in the same commit.

---

## 7. Throttle the Producer

```python
MIN_STEP = 5   # smallest change worth a database write and a publish


class ProgressReporter:
    def __call__(self, percent: int) -> None:
        if percent - self._last < MIN_STEP and percent < 100:
            return
        self._last = percent
        self.report.progress = percent
        self.report.save(update_fields=("progress", "modified"))
        publish_state(self.report)
```

A builder looping over a few hundred items and reporting each one would otherwise cost one `UPDATE` and one
HTTP call per item. Always publish the terminal states — completion and failure — regardless of step size.

---

## 8. Configuration

| Setting | Audience | Notes |
|---|---|---|
| `CENTRIFUGO_URL` | server → server | the HTTP API the app publishes to; internal hostname |
| `CENTRIFUGO_WEBSOCKETS_URL` | browser | what the client connects to; public, handed to the front-end |
| `CENTRIFUGO_API_KEY` | server → server | authorises publishing |
| `CENTRIFUGO_TOKEN_HMAC_SECRET_KEY` | shared secret | signs connection tokens |
| `CENTRIFUGO_TIMEOUT` | publish call | keep it low |

> ⚠️ The two URLs are not interchangeable — one is an internal service address, the other is what a browser
> can reach. Publishing to the public URL, or handing the browser the internal one, fails in ways that look
> like a network problem.

Both secrets live in environment files and are deployed alongside the websocket service's own config; they
must match on both sides or every connection is rejected with no useful error. The service config file
belongs in the repository, its secrets do not — the committed copy carries development placeholders only.

---

## 9. Testing

Real-time is an accelerator, so tests concentrate on the parts that are not:

- **Channel naming and parsing** — round-trip `user_channel` / `parse_user_channel`, plus the rejections:
  unknown prefix, wrong shape, non-numeric id.
- **Subscribe authorisation** — a user's own channel is accepted, another user's is refused, and both come
  back as 200 with the right body.
- **The token** — carries the caller's id, is signed with the configured secret, and expires.
- **Publish failure does not break the caller** — patch the client to raise and assert the job still
  completes and the row is still correct.
- **Payload parity** — assert the polling endpoint returns exactly what the publisher sends. This is the
  test that catches the two drifting apart.

Patch `publish` in tests that are not about publishing; there is no websocket server in the test environment.

---

## 10. Checklist

- [ ] Django still WSGI — no socket handling added to the app.
- [ ] Channel is per user, prefix whitelisted and free of underscores.
- [ ] Token carries `request.user.id`, never a client-supplied id, and expires.
- [ ] Subscribe proxy unauthenticated, answers 200 both ways, unreachable from outside.
- [ ] `publish()` logs and swallows transport failures, with a short timeout.
- [ ] Database written before publishing; polling endpoint returns the identical payload.
- [ ] Progress throttled; terminal states always published.
- [ ] Internal and public URLs kept distinct; secrets only in env files.
- [ ] Tests cover naming, authorisation, publish failure and payload parity.

## Navigation
- [Celery Tasks](../celery-tasks/SKILL.md)
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django Testing](../django-testing/SKILL.md)
- [Agent Configuration](../agent-configuration/SKILL.md)
