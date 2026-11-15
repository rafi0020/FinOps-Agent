export const money = (v: number | null | undefined, compact = true) =>
  v == null ? "no data" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: compact ? "compact" : "standard", maximumFractionDigits: compact ? 2 : 0 }).format(v);
export const pct = (v: number | null | undefined, digits = 1) => (v == null ? "no data" : `${(v * 100).toFixed(digits)}%`);
export const points = (v: number | null | undefined) => (v == null ? "" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)} pts`);
export const signedPct = (v: number | null | undefined) => (v == null ? "" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
export const num = (v: number | null | undefined, digits = 0) => (v == null ? "no data" : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(v));
export const usd = (v: number) => `$${v < 0.01 && v > 0 ? v.toFixed(4) : v.toFixed(2)}`;
export const duration = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
export const when = (iso: string) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
export const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
export function cell(v: unknown): string {
  if (v == null) return "null";
  if (typeof v === "number") return Number.isInteger(v) ? num(v) : Math.abs(v) < 1 ? v.toFixed(4) : num(v, 2);
  return String(v);
}
export const STATUS_LABEL: Record<string, string> = {
  queued: "Queued", running: "Working", waiting_approval: "Waiting for approval", waiting_user: "Waiting for your answer",
  completed: "Completed", failed: "Failed", cancelled: "Cancelled", budget_exceeded: "Stopped at a limit",
};
export const METRIC_LABEL: Record<string, string> = { revenue: "Revenue", gross_margin: "Gross margin", operating_margin: "Operating margin", discount_rate: "Discount rate", dso: "Days sales outstanding" };
export const metricValue = (metric: string, v: number) => (metric === "revenue" ? money(v) : metric === "dso" ? `${v.toFixed(1)} days` : pct(v));
