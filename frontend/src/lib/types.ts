export type Role = "viewer" | "analyst" | "admin";
export interface User { id: string; org_id: string; email: string; name: string; role: Role }
export interface Kpi { value: number | null; previous: number | null; change_vs_prev: number | null }
export interface Overview {
  period: string;
  kpis: { revenue: Kpi; gross_margin: Kpi; operating_margin: Kpi; dso: Kpi };
  revenue_by_month: { month: string; revenue: number | null; budget: number | null }[];
  margin_by_region: { region: string; revenue: number; gross_margin: number | null; operating_margin: number | null }[];
  top_customers: { name: string; segment: string; region: string; revenue: number }[];
}
export interface Step {
  idx: number; kind: "model" | "tool" | "note"; name: string; state: string; error: string | null;
  input: Record<string, unknown> | null; summary: string; handle: string | null; tool_calls: string[];
  tokens: number; cost_usd?: number; latency_ms: number;
}
export interface NumberRef { text: string; handle: string }
export interface ChartSpec { kind: "line" | "bar" | "waterfall"; title: string; x: string; labels: string[]; series: { name: string; data: (number | null)[] }[]; handle?: string; chart_handle?: string }
export interface Report {
  outcome: "answered" | "cannot_answer"; summary: string; summary_numbers: NumberRef[];
  findings: { number: number; claim: string; evidence: string[]; numbers: NumberRef[] }[];
  recommendations: string[]; charts: ChartSpec[]; unsupported: string[];
  evidence: { handle: string; kind: string; purpose: string | null; sql: string | null; row_count: number }[];
}
export type RunStatus = "queued" | "running" | "waiting_approval" | "waiting_user" | "completed" | "failed" | "cancelled" | "budget_exceeded";
export interface Run {
  id: string; question: string; status: RunStatus; error: string | null; pending: { kind?: string; question?: string; tool?: string } | null;
  steps_used: number; tokens_used: number; cost_usd: number; asked_by: string | null; user_id: string | null;
  created_at: string; finished_at: string | null; steps?: Step[]; report?: Report | null;
}
export interface Evidence { handle: string; kind: string; sql: string | null; row_count: number; payload: Record<string, unknown> & { columns?: string[]; rows?: unknown[][]; rows_omitted?: number } }
export interface Approval { id: string; run_id: string; question: string; tool: string; arguments: Record<string, unknown>; status: string; reason: string | null; requested_by: string | null; created_at: string; decided_at: string | null }
export interface AlertRule { id: string; metric: string; comparison: string; threshold: number; window: string; region: string | null; rationale: string; status: string; run_id: string | null; created_by: string | null; created_at: string }
export interface AlertEvent { id: string; rule: AlertRule; period: string; value: number; created_at: string; acknowledged: boolean }
export interface Investigation { id: string; run_id: string; title: string; pinned: boolean; question: string; outcome: string | null; summary: string; created_by: string | null; created_by_id: string | null; created_at: string }
