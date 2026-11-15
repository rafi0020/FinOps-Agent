"use client";

import { useState } from "react";
import { Chart } from "@/components/Chart";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading } from "@/components/ui";
import { useApi } from "@/lib/api";
import { duration, num, usd } from "@/lib/format";

interface Usage {
  scope: string;
  items: { key: string; model_calls: number; runs: number; tokens_in: number; tokens_out: number; cost_usd: number; avg_latency_ms: number }[];
  totals: { model_calls: number; tokens_in: number; tokens_out: number; cost_usd: number };
  budget: { org_daily_cost_usd: number; org_spent_today_usd: number | null; run_max_cost_usd: number; run_max_steps: number };
}
const GROUPS = [["day", "By day"], ["user", "By person"], ["model", "By model"]] as const;

export default function UsagePage() {
  const [group, setGroup] = useState<"day" | "user" | "model">("day");
  const { data, error, isLoading, mutate } = useApi<Usage>(`/api/usage?group=${group}`, { keepPreviousData: true });
  const column = group === "day" ? "Day" : group === "user" ? "Person" : "Model";
  return (
    <Page title="Usage" lede={`Model calls, tokens and estimated cost over the last 30 days${data ? (data.scope === "you" ? ", for your own runs." : ", for the whole organisation.") : "."} Cost is an estimate from the prices set in Administration.`}>
      {error && <ErrorState error={error} retry={() => mutate()} />}
      {isLoading && !data && <Loading rows={6} />}
      {data && (
        <div className="briefing">
          <div className="briefing__main">
            <section className="statement" aria-labelledby="period-summary">
              <div className="statement__head">
                <h2 id="period-summary">Period summary</h2>
                <span className="label">Last 30 days</span>
              </div>
              <dl className="figures">
                <div><dt>Model calls</dt><dd className="reading">{num(data.totals.model_calls)}</dd></div>
                <div><dt>Tokens in</dt><dd className="reading">{num(data.totals.tokens_in)}</dd></div>
                <div><dt>Tokens out</dt><dd className="reading">{num(data.totals.tokens_out)}</dd></div>
                <div>
                  <dt>Estimated cost</dt>
                  <dd className="reading">{usd(data.totals.cost_usd)}</dd>
                  {data.budget.org_spent_today_usd != null && <span className="figures__note measured">{usd(data.budget.org_spent_today_usd)} of {usd(data.budget.org_daily_cost_usd)} daily limit used today</span>}
                </div>
              </dl>
            </section>
            <div className="tabs" role="tablist">
              {GROUPS.map(([value, label]) => (<button key={value} className="tab" role="tab" aria-selected={group === value} onClick={() => setGroup(value)}>{label}</button>))}
            </div>
            {data.items.length === 0 && <Empty title="No model usage in this period">Usage appears once someone asks the agent a question.</Empty>}
            {data.items.length > 0 && (
              <div className="table-wrap">
                <table className="table statement-table">
                  <caption className="visually-hidden">Line items {group === "day" ? "by day" : group === "user" ? "by person" : "by model"}</caption>
                  <thead><tr><th>{column}</th><th className="num">Runs</th><th className="num">Model calls</th><th className="num">Tokens in</th><th className="num">Tokens out</th><th className="num">Avg latency</th><th className="num">Est. cost</th></tr></thead>
                  <tbody>
                    {data.items.map((i) => (
                      <tr key={i.key}><td className={group === "user" ? "" : "measured"}>{i.key}</td><td className="num">{i.runs}</td><td className="num">{i.model_calls}</td><td className="num">{num(i.tokens_in)}</td><td className="num">{num(i.tokens_out)}</td><td className="num">{duration(i.avg_latency_ms)}</td><td className="num">{usd(i.cost_usd)}</td></tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr><td>Period total</td><td /><td className="num">{num(data.totals.model_calls)}</td><td className="num">{num(data.totals.tokens_in)}</td><td className="num">{num(data.totals.tokens_out)}</td><td /><td className="num">{usd(data.totals.cost_usd)}</td></tr>
                  </tfoot>
                </table>
              </div>
            )}
          </div>
          <aside className="briefing__margin">
            {group === "day" && data.items.length > 1 && (
              <section className="grid gap-2" aria-labelledby="cost-by-day">
                <h2 id="cost-by-day">Estimated cost by day, USD</h2>
                <Chart spec={{ kind: "bar", title: "Estimated cost by day", x: "day", labels: data.items.map((i) => i.key.slice(5)), series: [{ name: "Cost", data: data.items.map((i) => i.cost_usd) }] }} />
              </section>
            )}
            <p className="limits">Limits: {data.budget.run_max_steps} model steps and {usd(data.budget.run_max_cost_usd)} per run; {usd(data.budget.org_daily_cost_usd)} per organisation per day.</p>
          </aside>
        </div>
      )}
    </Page>
  );
}
