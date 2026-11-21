// Adjuntos del chat (IA-6): el archivo va del navegador a Supabase Storage con una URL firmada.
// 1. POST /projects/{id}/attachments → {id, kind, upload_url, content_type}
// 2. PUT upload_url con el archivo y ese Content-Type
// 3. POST /projects/{id}/attachments/{aid}/complete → 204
export type AttachmentKind = "image" | "log";

export interface AttachmentUpload {
  id: string;
  kind: AttachmentKind;
  upload_url: string;
  content_type: string;
  expires_at: string;
}

export interface AttachmentInfo {
  id: string;
  kind: AttachmentKind;
  filename: string;
  bytes: number | null;
  created_at: string;
  expires_at: string;
}

export function createAttachmentsApi(
  baseURL: string,
  getAccessToken?: () => Promise<string | undefined>,
) {
  const fetchApi = $fetch.create({
    baseURL,
    retry: 0,
    timeout: 30_000,
    async onRequest({ options }) {
      if (!getAccessToken) return;
      const token = await getAccessToken();
      if (!token) throw new Error("Tu sesión expiró. Vuelve a iniciar sesión.");
      options.headers.set("Authorization", `Bearer ${token}`);
    },
  });
  const path = (projectId: string) =>
    `/projects/${encodeURIComponent(projectId)}/attachments`;

  return {
    create: (projectId: string, file: File) =>
      fetchApi<AttachmentUpload>(path(projectId), {
        method: "POST",
        body: { filename: file.name, media_type: file.type, bytes: file.size },
      }),
    /** Sube directo a Storage: la URL firmada ya lleva el permiso, sin token de sesión. */
    async upload(upload: AttachmentUpload, file: File) {
      const response = await fetch(upload.upload_url, {
        method: "PUT",
        headers: { "Content-Type": upload.content_type },
        body: file,
      });
      if (!response.ok)
        throw new Error(
          "El almacenamiento rechazó el archivo. Vuelve a subirlo.",
        );
    },
    complete: (projectId: string, id: string) =>
      fetchApi(`${path(projectId)}/${encodeURIComponent(id)}/complete`, {
        method: "POST",
      }),
    list: (projectId: string) => fetchApi<AttachmentInfo[]>(path(projectId)),
    remove: (projectId: string, id: string) =>
      fetchApi(`${path(projectId)}/${encodeURIComponent(id)}`, {
        method: "DELETE",
      }),
  };
}

export type AttachmentsApi = ReturnType<typeof createAttachmentsApi>;
