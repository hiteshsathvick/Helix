"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { type ChangeEvent, useState } from "react";
import { Alert, Button, EmptyState, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import {
  deleteDocument,
  listDocuments,
  reindexDocument,
  uploadDocument,
} from "@/lib/documents-api";
import { getMyPermissions } from "@/lib/orgs-api";

export default function DocumentsPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const documentsQuery = useQuery({
    queryKey: ["documents", orgId, accessToken],
    queryFn: () => listDocuments(accessToken!, orgId),
    enabled: !!accessToken,
    // Ingestion runs asynchronously in a worker — keep polling while
    // anything is still "pending" so status/reindex reflect real progress
    // without a manual reload; stop once everything has settled.
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === "pending") ? 3000 : false,
  });

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const invalidateDocuments = () =>
    queryClient.invalidateQueries({ queryKey: ["documents", orgId] });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(accessToken!, orgId, documentId),
    onSuccess: invalidateDocuments,
  });

  const reindexMutation = useMutation({
    mutationFn: (documentId: string) => reindexDocument(accessToken!, orgId, documentId),
    onSuccess: invalidateDocuments,
  });

  const canWrite = permissionsQuery.data?.permissions.includes("documents:write") ?? false;
  const documents = documentsQuery.data ?? [];

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !accessToken) return;
    setUploadError(null);
    setUploading(true);
    try {
      await uploadDocument(accessToken, orgId, file);
      invalidateDocuments();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "failed to upload document");
    } finally {
      setUploading(false);
    }
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Documents</h1>

      {documentsQuery.isLoading && <Spinner label="Loading documents…" />}
      {documentsQuery.isError && (
        <Alert>
          {documentsQuery.error instanceof Error
            ? documentsQuery.error.message
            : "failed to load documents"}
        </Alert>
      )}
      {documentsQuery.isSuccess && documents.length === 0 && (
        <EmptyState>No documents yet.</EmptyState>
      )}
      <ul data-testid="document-list" className="flex w-full max-w-md flex-col gap-2">
        {documents.map((document) => (
          <li key={document.id} className="flex items-center justify-between gap-3">
            <span data-testid={`document-status-${document.id}`}>
              {document.title} ({document.status})
            </span>
            {canWrite && (
              <span className="flex gap-2">
                <Button variant="link" onClick={() => reindexMutation.mutate(document.id)}>
                  Reindex
                </Button>
                <Button variant="danger" onClick={() => deleteMutation.mutate(document.id)}>
                  Delete
                </Button>
              </span>
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
          {uploading && <Spinner label="Uploading…" />}
          {uploadError && <Alert data-testid="upload-error">{uploadError}</Alert>}
        </div>
      )}
    </>
  );
}
