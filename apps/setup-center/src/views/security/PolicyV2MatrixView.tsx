// C23 P2-1: Policy V2 自动批准矩阵 UI
//
// Plan §13 / R5-12 / C9 要求 SecurityView 暴露给用户的两层结构:
//   1. session_role (4): plan / ask / agent / coordinator
//      —— PLAN / ASK 模式禁止任何 write intent, 不管 confirmation_mode 是什么
//   2. confirmation_mode (5) × ApprovalClass (11):
//      —— 给出 "在 X 模式下, Y 类操作自动 (ALLOW / CONFIRM / DENY)"
//
// 这个组件**不是 live editor** —— 它从后端
// /api/config/security/approval-matrix 读取 baseline 矩阵，让 UI 跟随
// policy_v2.matrix.lookup 的真相源。具体运行时决策还会叠加
// safety_immune / unattended / mode_ruleset 等条件。
//
// 与后端一致性守卫: tests/unit/test_c23_policy_v2_matrix.py 会确认
// API 覆盖所有 enum 值，并检查组件仍读取该 API。

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type Decision = "allow" | "confirm" | "deny";

type MatrixRow = {
  role: string;
  approval_class: string;
  decisions: Record<string, Decision>;
};

type MatrixResponse = {
  roles: string[];
  modes: string[];
  classes: string[];
  rows: MatrixRow[];
  baseline_only: boolean;
};

const DECISION_META: Record<Decision, { color: string; bg: string }> = {
  allow:   { color: "#16a34a", bg: "#22c55e1a" },
  confirm: { color: "#d97706", bg: "#f59e0b1a" },
  deny:    { color: "#dc2626", bg: "#ef44441a" },
};

function DecisionCell({ decision }: { decision: Decision }) {
  const { t } = useTranslation();
  const meta = DECISION_META[decision];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 0,
        color: meta.color,
        background: meta.bg,
        border: `1px solid ${meta.color}44`,
      }}
    >
      {t(`security.decision.${decision}`)}
    </span>
  );
}

export function PolicyV2MatrixView({ apiBaseUrl }: { apiBaseUrl: string }) {
  const { t } = useTranslation();
  const [data, setData] = useState<MatrixResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBaseUrl}/api/config/security/approval-matrix`)
      .then((res) => res.json())
      .then((json) => {
        if (!cancelled) setData(json);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  const groupedRows = useMemo(() => {
    const rows = data?.rows || [];
    return (data?.roles || []).map((role) => ({
      role,
      rows: rows.filter((row) => row.role === role),
    }));
  }, [data]);

  return (
    <div className="space-y-4">
      {/* Session role panel */}
      <Card className="p-0 gap-0 border-border/50 shadow-sm">
        <CardHeader className="border-b border-border/50 px-4 py-2.5">
          <CardTitle className="text-sm font-semibold">
            {t("security.matrixSessionRoleTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 px-4 py-3 text-xs">
          <p className="text-muted-foreground leading-5">
            {t("security.matrixSessionRoleDesc")}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {(data?.roles || []).map((role) => (
              <div
                key={role}
                className="rounded-md border border-border/50 bg-muted/30 px-3 py-2"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="outline" className="text-[10px] uppercase">{role}</Badge>
                  <span className="text-sm font-medium">
                    {t(`security.sessionRole.${role}`, role)}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {t("security.matrixRoleGenerated")}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ApprovalClass × ConfirmationMode 矩阵 */}
      <Card className="p-0 gap-0 border-border/50 shadow-sm">
        <CardHeader className="border-b border-border/50 px-4 py-2.5">
          <CardTitle className="text-sm font-semibold">
            {t("security.matrixTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 py-3 text-xs">
          <p className="text-muted-foreground leading-5 mb-3">
            {t("security.matrixDesc")}
          </p>
          {error && <p className="text-xs text-destructive">{error}</p>}
          {!data && !error && (
            <p className="text-xs text-muted-foreground">{t("security.matrixLoading")}</p>
          )}
          {data && <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-border/50">
                  <th className="text-left py-2 pr-3 font-medium text-muted-foreground">
                    {t("security.matrixColClass")}
                  </th>
                  {data.modes.map((mode) => (
                    <th key={mode} className="text-center py-2 px-2 font-medium">
                      <div className="text-sm">{t(`security.matrixMode.${mode}`, mode)}</div>
                      <div className="text-[10px] text-muted-foreground font-normal mt-0.5">confirmation_mode</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {groupedRows.flatMap(({ role, rows }) => [
                  <tr key={`${role}-header`} className="bg-muted/30">
                    <td colSpan={data.modes.length + 1} className="py-2 font-semibold uppercase">
                      {role}
                    </td>
                  </tr>,
                  ...rows.map((row) => (
                    <tr key={`${row.role}-${row.approval_class}`} className="border-b border-border/30 last:border-b-0">
                      <td className="py-2 pr-3">
                        <span className="text-xs" title={row.approval_class}>
                          {t(`security.approvalClass.${row.approval_class}`, row.approval_class)}
                        </span>
                      </td>
                      {data.modes.map((mode) => (
                        <td key={mode} className="text-center py-2 px-2">
                          <DecisionCell decision={row.decisions[mode]} />
                        </td>
                      ))}
                    </tr>
                  )),
                ])}
              </tbody>
            </table>
          </div>}

          {/* Legend */}
          <div className="flex flex-wrap items-center gap-3 mt-4 pt-3 border-t border-border/50 text-[11px]">
            <span className="text-muted-foreground">{t("security.matrixLegend")}</span>
            <span className="inline-flex items-center gap-1.5">
              <DecisionCell decision="allow" />
              <span>{t("security.matrixLegendAllow")}</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <DecisionCell decision="confirm" />
              <span>{t("security.matrixLegendConfirm")}</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <DecisionCell decision="deny" />
              <span>{t("security.matrixLegendDeny")}</span>
            </span>
          </div>

          <p className="text-[10px] text-muted-foreground mt-3 italic">
            {t("security.matrixDataSource")}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

// Matrix data now comes from /api/config/security/approval-matrix.
