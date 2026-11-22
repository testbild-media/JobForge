"""Webhook-Versand: JSON-POST mit HMAC-SHA256-Signatur, asynchron nach Commit."""
import hashlib
import hmac
import json
import logging
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

log = logging.getLogger("jobforge.webhooks")
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook")
_disabled = threading.local()


def serialize(instance):
    try:
        from api.serializers import serializer_for

        ser = serializer_for(type(instance))
        if ser is not None:
            return ser(instance).data
    except Exception:  # pragma: no cover - Fallback, falls Serialisierung fehlschlägt
        log.exception("Webhook-Serialisierung fehlgeschlagen")
    return {"id": instance.pk, "repr": str(instance)}


def _deliver(webhook_id, event, body):
    from .models import Webhook, WebhookDelivery

    try:
        webhook = Webhook.objects.get(pk=webhook_id)
    except Webhook.DoesNotExist:
        return
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"JobForge/{settings.VERSION}",
        "X-JobForge-Event": event,
    }
    if webhook.secret:
        sig = hmac.new(webhook.secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-JobForge-Signature"] = f"sha256={sig}"
    status, ok, text = None, False, ""
    try:
        req = urllib.request.Request(webhook.url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            text = resp.read(2000).decode("utf-8", "replace")
            ok = 200 <= status < 300
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read(2000).decode("utf-8", "replace")
    except Exception as e:  # Netzwerkfehler etc.
        text = str(e)
    WebhookDelivery.objects.create(webhook=webhook, event=event, status_code=status, success=ok, response=text[:2000])
    # Nur die letzten 200 Zustellungen je Webhook behalten
    old = webhook.deliveries.order_by("-timestamp").values_list("pk", flat=True)[200:]
    if old:
        WebhookDelivery.objects.filter(pk__in=list(old)).delete()


def trigger(event, instance, deleted=False):
    if getattr(_disabled, "value", False):
        return
    from .models import Webhook

    try:
        hooks = [w for w in Webhook.objects.filter(active=True) if w.matches(event)]
    except Exception:
        return
    if not hooks:
        return
    data = {"id": instance.pk, "repr": str(instance)} if deleted else serialize(instance)
    payload = {"event": event, "timestamp": timezone.now(), "data": data}
    body = json.dumps(payload, cls=DjangoJSONEncoder).encode()

    def send():
        for hook in hooks:
            _executor.submit(_deliver, hook.pk, event, body)

    transaction.on_commit(send)


def send_test(webhook):
    body = json.dumps(
        {"event": "ping", "timestamp": timezone.now(), "data": {"message": "JobForge Webhook-Test"}},
        cls=DjangoJSONEncoder,
    ).encode()
    _deliver(webhook.pk, "ping", body)
