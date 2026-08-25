"use client";

import { useParams } from "next/navigation";
import { type ChangeEvent, useCallback, useEffect, useState } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/lib/auth-context";
import { deleteDocument, listDocuments, uploadDocument, type Document } from "@/lib/documents-api";
import { getMyPermissions } from "@/lib/orgs-api";

function DocumentsContent() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [documents, setDocuments] = useState<Document[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const loadDocuments = useCallback(() => {
    if (!accessToken) return;
    listDocuments(accessToken, orgId)
      .then(setDocuments)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "failed to load documents"));
  }, [accessToken, orgId]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    if (!accessToken) return;
    getMyPermissions(accessToken, orgId)
      .then((data) => setPermissions(data.permissions))
      .catch(() => setPermissions([]));
  }, [accessToken, orgId]);

  const canWrite = permissions.includes("documents:write");

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !accessToken) return;
    setUploadError(null);
    setUploading(true);
    try {
      await uploadDocument(accessToken, orgId, file);
      loadDocuments();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "failed to upload document");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId: string) {
    if (!accessToken) return;
    await deleteDocument(accessToken, orgId, documentId);
    loadDocuments();
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-24">
      <h1 className="text-2xl font-semibold">Documents</h1>

      {loadError && <p className="text-red-600">{loadError}</p>}
      <ul data-testid="document-list" className="flex w-full max-w-md flex-col gap-2">
        {documents.map((document) => (
          <li key={document.id} className="flex items-center justify-between gap-3">
            <span>
              {document.title} ({document.status})
            </span>
            {canWrite && (
              <button
                onClick={() => handleDelete(document.id)}
                className="text-sm text-red-600 underline"
              >
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>

      {canWrite && (
        <div className="flex flex-col items-center gap-2">
          <input
            type="file"
            onChange={handleFileChange}
            disabled={uploading}
            data-testid="upload-input"
          />
          {uploading && <p>Uploading…</p>}
          {uploadError && (
            <p data-testid="upload-error" className="text-red-600">
              {uploadError}
            </p>
          )}
        </div>
      )}
    </main>
  );
}

export default function DocumentsPage() {
  return (
    <ProtectedRoute>
      <DocumentsContent />
    </ProtectedRoute>
  );
}
