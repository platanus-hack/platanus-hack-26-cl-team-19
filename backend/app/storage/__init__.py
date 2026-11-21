"""Archivos que el usuario sube al chat (IA-6): imágenes y logs en Supabase Storage."""

from app.storage.attachments import AttachmentStorage, InMemoryAttachmentStorage, StorageError

__all__ = ["AttachmentStorage", "InMemoryAttachmentStorage", "StorageError"]
