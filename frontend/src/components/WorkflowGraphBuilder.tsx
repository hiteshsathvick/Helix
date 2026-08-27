"use client";

import { NODE_TYPES, type WorkflowEdge, type WorkflowGraph, type WorkflowNode } from "@/lib/workflows-api";
import { Button, Input } from "@/components/ui";

// Structured form-based DAG builder (Phase 13 v1): each node's id/type is a
// real form field, edges are wired via dropdowns referencing other node
// ids, and only a node's type-specific `config` (which varies wildly by
// type — a tool name + args for "action", an operator + path for
// "condition", instructions for "ai") is a raw JSON textarea. This ships
// without a new drag-and-drop/canvas dependency (none exists in this repo
// yet); the graph JSON contract stays identical if a visual canvas
// replaces this UI later.
export function WorkflowGraphBuilder({
  value,
  onChange,
}: {
  value: WorkflowGraph;
  onChange: (graph: WorkflowGraph) => void;
}) {
  function updateNode(index: number, patch: Partial<WorkflowNode>) {
    const nodes = value.nodes.map((node, i) => (i === index ? { ...node, ...patch } : node));
    onChange({ ...value, nodes });
  }

  function updateNodeConfig(index: number, raw: string) {
    try {
      updateNode(index, { config: JSON.parse(raw || "{}") });
    } catch {
      // Invalid JSON mid-edit is expected while typing -- leave config
      // as-is rather than losing keystrokes; the config a user can't get
      // to parse will surface as a 422 from the server's own validation.
    }
  }

  function addNode() {
    const id = `node_${value.nodes.length + 1}`;
    onChange({ ...value, nodes: [...value.nodes, { id, type: "action", config: {} }] });
  }

  function removeNode(index: number) {
    const removedId = value.nodes[index]?.id;
    onChange({
      ...value,
      nodes: value.nodes.filter((_, i) => i !== index),
      edges: value.edges.filter((edge) => edge.from !== removedId && edge.to !== removedId),
    });
  }

  function updateEdge(index: number, patch: Partial<WorkflowEdge>) {
    const edges = value.edges.map((edge, i) => (i === index ? { ...edge, ...patch } : edge));
    onChange({ ...value, edges });
  }

  function addEdge() {
    const first = value.nodes[0]?.id ?? "";
    onChange({ ...value, edges: [...value.edges, { from: first, to: first, condition: null }] });
  }

  function removeEdge(index: number) {
    onChange({ ...value, edges: value.edges.filter((_, i) => i !== index) });
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-sm font-medium">Nodes</h3>
        <div className="mt-2 flex flex-col gap-2">
          {value.nodes.map((node, index) => (
            <div key={index} className="flex flex-col gap-2 rounded border p-3" data-testid={`node-row-${index}`}>
              <div className="flex gap-2">
                <Input
                  type="text"
                  placeholder="Node id"
                  value={node.id}
                  onChange={(event) => updateNode(index, { id: event.target.value })}
                  data-testid={`node-id-${index}`}
                  className="flex-1"
                />
                <select
                  value={node.type}
                  onChange={(event) =>
                    updateNode(index, { type: event.target.value as WorkflowNode["type"] })
                  }
                  data-testid={`node-type-${index}`}
                  className="rounded border px-2"
                >
                  {NODE_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
                <Button type="button" variant="secondary" onClick={() => removeNode(index)}>
                  Remove
                </Button>
              </div>
              <textarea
                placeholder='Config (JSON), e.g. {"tool": "notify", "args": {"channel": "c", "message": "hi"}}'
                defaultValue={JSON.stringify(node.config)}
                onBlur={(event) => updateNodeConfig(index, event.target.value)}
                data-testid={`node-config-${index}`}
                className="rounded border px-3 py-2 font-mono text-xs"
                rows={2}
              />
            </div>
          ))}
        </div>
        <Button type="button" variant="secondary" onClick={addNode} className="mt-2">
          + Add node
        </Button>
      </div>

      <div>
        <h3 className="text-sm font-medium">Edges</h3>
        <div className="mt-2 flex flex-col gap-2">
          {value.edges.map((edge, index) => (
            <div key={index} className="flex items-center gap-2" data-testid={`edge-row-${index}`}>
              <select
                value={edge.from}
                onChange={(event) => updateEdge(index, { from: event.target.value })}
                className="rounded border px-2"
                data-testid={`edge-from-${index}`}
              >
                {value.nodes.map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.id}
                  </option>
                ))}
              </select>
              <span className="text-sm text-gray-500">→</span>
              <select
                value={edge.to}
                onChange={(event) => updateEdge(index, { to: event.target.value })}
                className="rounded border px-2"
                data-testid={`edge-to-${index}`}
              >
                {value.nodes.map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.id}
                  </option>
                ))}
              </select>
              <select
                value={edge.condition ?? ""}
                onChange={(event) =>
                  updateEdge(index, {
                    condition: (event.target.value || null) as WorkflowEdge["condition"],
                  })
                }
                className="rounded border px-2"
                data-testid={`edge-condition-${index}`}
              >
                <option value="">always</option>
                <option value="true">if true</option>
                <option value="false">if false</option>
              </select>
              <Button type="button" variant="secondary" onClick={() => removeEdge(index)}>
                Remove
              </Button>
            </div>
          ))}
        </div>
        <Button type="button" variant="secondary" onClick={addEdge} className="mt-2">
          + Add edge
        </Button>
      </div>
    </div>
  );
}
