// Borradores de adjuntos del compositor del chat (IA-9). Valida tipo y tamaño antes de pedir la URL,
// sube en paralelo y deja cada uno en uploading, ready o error.
import {
  createAttachmentsApi,
  type AttachmentKind,
  type AttachmentsApi,
} from "@/services/attachments-api";

export const MAX_ATTACHMENTS = 5;
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_LOG_BYTES = 10 * 1024 * 1024;
export const IMAGE_TYPES = [
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
];
export const LOG_EXTENSIONS = [".log", ".txt", ".csv", ".json", ".ndjson"];
const LOG_TYPES = [
  "text/plain",
  "text/csv",
  "application/json",
  "application/x-ndjson",
];

export type DraftStatus = "uploading" | "ready" | "error";

export interface AttachmentDraft {
  localId: string;
  name: string;
  size: number;
  kind: AttachmentKind;
  status: DraftStatus;
  id?: string;
  error?: string;
  previewUrl?: string;
}

/** El tipo del archivo, o el motivo por el que no se acepta. */
export function classifyFile(
  file: Pick<File, "name" | "type" | "size">,
): { kind: AttachmentKind } | { error: string } {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  const kind: AttachmentKind | null = IMAGE_TYPES.includes(file.type)
    ? "image"
    : LOG_TYPES.includes(file.type) || LOG_EXTENSIONS.includes(ext)
      ? "log"
      : null;
  if (!kind)
    return {
      error:
        "Solo imágenes PNG, JPEG, WebP o GIF y logs .log, .txt, .csv, .json o .ndjson.",
    };
  const max = kind === "image" ? MAX_IMAGE_BYTES : MAX_LOG_BYTES;
  if (file.size > max)
    return {
      error: `Pasa el límite de ${max / 1024 / 1024} MB para ${kind === "image" ? "imágenes" : "logs"}.`,
    };
  if (file.size === 0) return { error: "El archivo está vacío." };
  return { kind };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
}

function errorMessage(cause: unknown): string {
  const data = (cause as { data?: { error?: { message?: string } } })?.data;
  if (data?.error?.message) return data.error.message;
  return cause instanceof Error && cause.message
    ? cause.message
    : "No se pudo subir el archivo.";
}

function preview(file: File): string | undefined {
  if (!import.meta.client) return undefined;
  try {
    return URL.createObjectURL(file);
  } catch {
    return undefined; // sin miniatura: el chip sigue mostrando nombre y tamaño
  }
}

export function useChatAttachments(
  projectId: Ref<string | undefined>,
  options: { api?: AttachmentsApi; enabled?: boolean } = {},
) {
  let api = options.api;
  if (!api) {
    const baseURL = useRuntimeConfig().public.apiBase.trim();
    const auth = useSupabaseAuth();
    api =
      baseURL && auth.enabled
        ? createAttachmentsApi(baseURL, auth.getAccessToken)
        : undefined;
  }
  const enabled = options.enabled ?? Boolean(api);
  const drafts = ref<AttachmentDraft[]>([]);
  const uploading = computed(() =>
    drafts.value.some((draft) => draft.status === "uploading"),
  );
  const ready = computed(() =>
    drafts.value.filter(
      (draft): draft is AttachmentDraft & { id: string } =>
        draft.status === "ready" && Boolean(draft.id),
    ),
  );

  function update(localId: string, changes: Partial<AttachmentDraft>) {
    const draft = drafts.value.find((item) => item.localId === localId);
    if (draft) Object.assign(draft, changes);
  }

  async function upload(localId: string, file: File) {
    const id = projectId.value;
    if (!api || !id) return;
    try {
      const target = await api.create(id, file);
      update(localId, { id: target.id });
      await api.upload(target, file);
      await api.complete(id, target.id);
      update(localId, { status: "ready" });
    } catch (cause) {
      update(localId, { status: "error", error: errorMessage(cause) });
    }
  }

  /** Agrega y sube los archivos. Los que pasan el tope de 5 no se agregan; devuelve cuántos quedaron fuera. */
  function add(files: Iterable<File>): number {
    if (!enabled) return 0;
    let skipped = 0;
    const jobs: Promise<void>[] = [];
    for (const file of files) {
      if (drafts.value.length >= MAX_ATTACHMENTS) {
        skipped++;
        continue;
      }
      const checked = classifyFile(file);
      const localId = crypto.randomUUID();
      const kind = "kind" in checked ? checked.kind : "log";
      drafts.value.push({
        localId,
        name: file.name,
        size: file.size,
        kind,
        status: "error" in checked ? "error" : "uploading",
        error: "error" in checked ? checked.error : undefined,
        previewUrl:
          kind === "image" && "kind" in checked ? preview(file) : undefined,
      });
      if ("kind" in checked) jobs.push(upload(localId, file));
    }
    void Promise.all(jobs);
    return skipped;
  }

  function release(draft: AttachmentDraft) {
    if (draft.previewUrl && import.meta.client)
      URL.revokeObjectURL(draft.previewUrl);
  }

  function remove(localId: string) {
    const draft = drafts.value.find((item) => item.localId === localId);
    if (!draft) return;
    release(draft);
    drafts.value = drafts.value.filter((item) => item.localId !== localId);
    const id = projectId.value;
    if (api && id && draft.id && draft.status === "ready")
      void api.remove(id, draft.id).catch(() => undefined);
  }

  /** Después de enviar: los adjuntos quedan en el mensaje, no en el compositor. */
  function clear() {
    drafts.value.forEach(release);
    drafts.value = [];
  }

  onScopeDispose(clear);
  return { enabled, drafts, uploading, ready, add, remove, clear };
}
