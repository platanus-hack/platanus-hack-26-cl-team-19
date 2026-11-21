"""``AttachmentStorage`` contra el Storage real del stack local de Supabase (``npx supabase start``).

Corre solo con ``TEST_SUPABASE_URL`` y ``TEST_SUPABASE_SECRET_KEY`` (los de ``npx supabase status``);
el CI levanta solo la base y lo salta. Usa el bucket ``chat-attachments`` de la migración.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
import uuid

import pytest

from app.storage.attachments import AttachmentStorage, StorageError


@pytest.fixture
def storage():
    url, key = os.environ.get("TEST_SUPABASE_URL"), os.environ.get("TEST_SUPABASE_SECRET_KEY")
    if not url or not key:
        pytest.skip("sin TEST_SUPABASE_URL: se salta el test de Supabase Storage")
    return AttachmentStorage(url, key)


def test_signed_upload_head_download_delete(storage):
    path = f"test/{uuid.uuid4()}/access.log"
    data = b'127.0.0.1 - - [21/Nov/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 12\n'
    url = storage.signed_upload(path)
    req = urllib.request.Request(url, data=data, method="PUT", headers={"Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=10) as r:  # el navegador, sin auth
        assert r.status == 200
    assert storage.head(path) == (len(data), "text/plain")
    assert storage.download(path, 9) == data[:9]
    assert storage.download(path, 10_000) == data
    storage.delete([path])
    assert storage.head(path) is None
    with pytest.raises(StorageError):
        storage.download(path, 10)


def test_bucket_rejects_other_types(storage):
    url = storage.signed_upload(f"test/{uuid.uuid4()}/x.pdf")
    req = urllib.request.Request(url, data=b"%PDF", method="PUT", headers={"Content-Type": "application/pdf"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code in (400, 415)
