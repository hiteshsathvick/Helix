import { API_URL, toApiError } from "./api";

export type Document = {
  id: string;
  source_id: string;
  title: string;
  mime: string;
  status: string;
  checksum: string;
  uploaded_by_user_id: string;
  created_at: string;
};

export async function listDocuments(accessToken: string, orgId: string): Promise<Document[]> {
  const response = await fetch(`${API_URL}/api/v1/orgs/${orgId}/documents`, {
    credentials: "include",
    cache: "no-store",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function uploadDocument(
  accessToken: string,
  orgId: string,
  file: File
): Promise<Document> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_URL}/api/v1/orgs/${orgId}/documents`, {
    method: "POST",
    credentials: "include",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: formData,
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function deleteDocument(
  accessToken: string,
  orgId: string,
  documentId: string
): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/orgs/${orgId}/documents/${documentId}`, {
    method: "DELETE",
    credentials: "include",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await toApiError(response);
}
