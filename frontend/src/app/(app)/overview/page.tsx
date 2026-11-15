"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Chart } from "@/components/Chart";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading } from "@/components/ui";
import { useApi } from "@/lib/api";
import { money, pct, points, signedPct } from "@/lib/format";
import type { Kpi, Overview } from "@/lib/types";

const PERIODS = ["2026-Q3", "2026-Q2", "2026-Q1", "2025-Q4", "2026", "2025", "2024"];

function Stat({ label, value, delta, good }: { label: string; value: string; delta: string; good: boolean | null }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="reading">{value}</span>
      <span className={`stat__delta measured ${good == null ? "muted" : good ? "ok" : "bad"}`}>{delta ? `${delta} vs previous period` : "no previous period"}</span>
    </div>
  );
}

const rising = (k: Kpi) => (k.change_vs_prev == null || k.change_vs_prev === 0 ? null : k.change_vs_prev > 0);

function OverviewPage() {
  const router = useRouter();
  const period = useSearchParams().get("period") ?? "2026-Q3";
  const { data, error, isLoading, mutate } = useApi<Overview>(`/api/overview?period=${encodeURIComponent(period)}`);
  const k = data?.kpis;
  return (
    <Page
      title="Overview"
      lede="Headline figures calculated directly from the database with fixed queries. No model is involved on this screen."
      actions={
        <label className="field">
          <span className="visually-hidden">Period</span>
          <select className="select" value={period} onChange={(e) => router.replace(`/overview/?period=${e.target.value}`)}>
            {PERIODS.map((p) => (<option key={p}>{p}</option>))}
          </select>
        </label>
      }
    >
      {error && <ErrorState error={error} retry={() => mutate()} />}
      {isLoading && <div className="panel"><Loading rows={6} /></div>}
      {data && k && k.revenue.value == null && <div className="panel"><Empty title={`No sales recorded in ${period}`}>Choose another period. Data covers January 2024 to September 2026.</Empty></div>}
      {data && k && k.revenue.value != null && (
        <>
          <section className="panels stats" aria-label="Key figures">
            <Stat label="Revenue" value={money(k.revenue.value)} delta={signedPct(k.revenue.change_vs_prev)} good={rising(k.revenue)} />
            <Stat label="Gross margin" value={pct(k.gross_margin.value)} delta={points(k.gross_margin.change_vs_prev)} good={rising(k.gross_margin)} />
            <Stat label="Operating margin" value={pct(k.operating_margin.value)} delta={points(k.operating_margin.change_vs_prev)} good={rising(k.operating_margin)} />
            <Stat label="Days sales outstanding" value={k.dso.value == null ? "no data" : `${k.dso.value.toFixed(1)} d`}
              delta={k.dso.change_vs_prev == null ? "" : `${k.dso.change_vs_prev > 0 ? "+" : ""}${k.dso.change_vs_prev.toFixed(1)} days`}
              good={rising(k.dso) == null ? null : !rising(k.dso)} />
          </section>
          <section className="panel">
            <div className="panel__head"><h2>Revenue and plan, last twelve months</h2></div>
            <div className="panel__body">
              <Chart spec={{ kind: "line", title: "Revenue and plan by month", x: "month", labels: data.revenue_by_month.map((m) => m.month.slice(0, 7)),
                series: [{ name: "Revenue", data: data.revenue_by_month.map((m) => m.revenue) }, { name: "Plan", data: data.revenue_by_month.map((m) => m.budget) }] }} />
            </div>
          </section>
          <div className="grid gap-6 lg:grid-cols-2 items-start">
            <section className="panel table-wrap">
              <div className="panel__head"><h2>Margin by region</h2></div>
              <table className="table">
                <thead><tr><th>Region</th><th className="num">Revenue</th><th className="num">Gross margin</th><th className="num">Operating margin</th></tr></thead>
                <tbody>
                  {data.margin_by_region.map((r) => (
                    <tr key={r.region}><td>{r.region}</td><td className="num">{money(r.revenue)}</td><td className="num">{pct(r.gross_margin)}</td><td className="num">{pct(r.operating_margin)}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="panel table-wrap">
              <div className="panel__head"><h2>Largest customers</h2></div>
              <table className="table">
                <thead><tr><th>Customer</th><th>Segment</th><th>Region</th><th className="num">Revenue</th></tr></thead>
                <tbody>
                  {data.top_customers.map((c) => (
                    <tr key={c.name}><td>{c.name}</td><td className="muted">{c.segment}</td><td className="muted">{c.region}</td><td className="num">{money(c.revenue)}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
        </>
      )}
    </Page>
  );
}

export default function OverviewRoute() {
  return (<Suspense fallback={<Loading />}><OverviewPage /></Suspense>);
}
