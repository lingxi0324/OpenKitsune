export const ORG_STRUCTURE_CHANGED_EVENT = "openkitsune:org-structure-changed";

export type OrgStructureChangeAction = "created" | "updated" | "deleted";

export interface OrgStructureChangeDetail {
  action: OrgStructureChangeAction;
  orgId: string;
  orgName?: string;
  templateId?: string;
  nodeCount?: number;
  edgeCount?: number;
  status?: string;
  toolUseId?: string;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function numberValue(value: unknown): number | undefined {
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

export function normalizeOrgStructureChange(value: unknown): OrgStructureChangeDetail | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const orgId = stringValue(raw.org_id) || stringValue(raw.orgId);
  if (!orgId) return null;

  const rawAction = stringValue(raw.action) || "updated";
  const action: OrgStructureChangeAction =
    rawAction === "created" || rawAction === "deleted" ? rawAction : "updated";

  return {
    action,
    orgId,
    orgName: stringValue(raw.org_name) || stringValue(raw.orgName),
    templateId: stringValue(raw.template_id) || stringValue(raw.templateId),
    nodeCount: numberValue(raw.node_count ?? raw.nodeCount),
    edgeCount: numberValue(raw.edge_count ?? raw.edgeCount),
    status: stringValue(raw.status),
    toolUseId: stringValue(raw.tool_use_id) || stringValue(raw.toolUseId),
  };
}

export function dispatchOrgStructureChanged(value: unknown): boolean {
  const detail = normalizeOrgStructureChange(value);
  if (!detail) return false;
  window.dispatchEvent(new CustomEvent<OrgStructureChangeDetail>(ORG_STRUCTURE_CHANGED_EVENT, { detail }));
  return true;
}
