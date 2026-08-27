"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { AVAILABLE_TOOLS, createAgent, listAgents } from "@/lib/agents-api";
import { getMyPermissions } from "@/lib/orgs-api";

export default function AgentsPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  const agentsQuery = useQuery({
    queryKey: ["agents", orgId, accessToken],
    queryFn: () => listAgents(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const createMutation = useMutation({
    mutationFn: () => createAgent(accessToken!, orgId, name, instructions, selectedTools),
    onSuccess: () => {
      setName("");
      setInstructions("");
      setSelectedTools([]);
      queryClient.invalidateQueries({ queryKey: ["agents", orgId] });
    },
    onError: (err) => setFormError(err instanceof Error ? err.message : "failed to create agent"),
  });

  const canManage = permissionsQuery.data?.permissions.includes("agents:manage") ?? false;
  const agents = agentsQuery.data ?? [];

  function toggleTool(tool: string) {
    setSelectedTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool]
    );
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    if (!name.trim() || !instructions.trim()) return;
    createMutation.mutate();
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Agents</h1>

      {agentsQuery.isLoading && <Spinner label="Loading agents…" />}
      {agentsQuery.isError && (
        <Alert>
          {agentsQuery.error instanceof Error ? agentsQuery.error.message : "failed to load agents"}
        </Alert>
      )}
      {agentsQuery.isSuccess && agents.length === 0 && <EmptyState>No agents yet.</EmptyState>}

      <ul data-testid="agent-list" className="flex w-full max-w-md flex-col gap-2">
        {agents.map((agent) => (
          <li key={agent.id}>
            <Link
              href={`/orgs/${orgId}/agents/${agent.id}`}
              className="underline"
              data-testid={`agent-link-${agent.id}`}
            >
              {agent.name}
            </Link>
            <span className="ml-2 text-sm text-gray-500">
              ({agent.allowed_tools.join(", ") || "no tools"})
            </span>
          </li>
        ))}
      </ul>

      {canManage && (
        <form
          onSubmit={handleSubmit}
          className="flex w-full max-w-md flex-col gap-3 rounded border p-4"
        >
          <h2 className="font-medium">New agent</h2>
          <Input
            type="text"
            placeholder="Name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            data-testid="agent-name-input"
          />
          <textarea
            placeholder="Instructions — what should this agent do?"
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            data-testid="agent-instructions-input"
            className="rounded border px-3 py-2"
            rows={3}
          />
          <fieldset className="flex flex-col gap-1">
            <legend className="text-sm font-medium">Allowed tools</legend>
            {AVAILABLE_TOOLS.map((tool) => (
              <label key={tool} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedTools.includes(tool)}
                  onChange={() => toggleTool(tool)}
                  data-testid={`tool-checkbox-${tool}`}
                />
                {tool}
              </label>
            ))}
          </fieldset>
          <Button type="submit" disabled={createMutation.isPending} data-testid="create-agent-submit">
            {createMutation.isPending ? "Creating…" : "Create agent"}
          </Button>
          {formError && <Alert data-testid="create-agent-error">{formError}</Alert>}
        </form>
      )}
    </>
  );
}
