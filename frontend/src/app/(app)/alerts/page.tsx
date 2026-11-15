"use client";

import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading, StatusChip, useToast } from "@/components/ui";
import { api, ApiError, useApi, useMe } from "@/lib/api";
import { METRIC_LABEL, metricValue, when } from "@/lib/format";
import type { AlertEvent, AlertRule } from "@/lib/types";

/** The condition of a rule as one readable sentence, e.g. "Gross margin in West below 25.0%, per quarter". */
const describe = (r: AlertRule) => `${METRIC_LABEL[r.metric] ?? r.metric}${r.region ? ` in ${r.region}` : ""} ${r.comparison === "<" ? "below" : "above"} ${metricValue(r.metric, r.threshold)}, per ${r.window}`;

export default function AlertsPage() {
  const { user } = useMe();
  const toast = useToast();
  const events = useApi<{ events: AlertEvent[]; unacknowledged: number }>("/api/alerts/events");
  const rules = useApi<{ rules: AlertRule[] }>("/api/alerts/rules");
  const run = async (fn: () => Promise<unknown>, done: string) => {
    try { await fn(); toast(done); await Promise.all([events.mutate(), rules.mutate()]); } catch (e) { toast(e instanceof ApiError ? e.message : "That did not work.", "bad"); }
  };
  return (
    <Page title="Alerts" lede="Rules are proposed through the agent and take effect only after an administrator approves them. They are checked every 15 minutes; alerts appear here and nowhere else."
      actions={user?.role === "admin" && <button className="btn" onClick={() => run(async () => { const r = await api<{ raised: number }>("/api/alerts/evaluate", { method: "POST" }); toast(r.raised ? `${r.raised} new alert${r.raised > 1 ? "s" : ""}.` : "No new alerts."); }, "Rules checked.")}>Check rules now</button>}>
      <div className="briefing">
        <div className="briefing__main">
          <section className="grid gap-2" aria-labelledby="standing-orders">
            <h2 id="standing-orders">Standing orders</h2>
            {rules.isLoading && <Loading />}
            {rules.error && <ErrorState error={rules.error} retry={() => rules.mutate()} />}
            {rules.data?.rules.length === 0 && (
              <Empty title="No alert rules yet">Ask the agent, for example: &ldquo;Alert me if West gross margin drops below 25% in a quarter.&rdquo;
                {user?.role !== "viewer" && <a className="btn btn--primary" href="/ask/">Ask the agent</a>}
              </Empty>
            )}
            {!!rules.data?.rules.length && (
              <div className="orders">
                {rules.data.rules.map((r) => (
                  <article key={r.id} className="order">
                    <h3 className="order__condition">{describe(r)}</h3>
                    <dl className="facts">
                      <dt>State</dt><dd><StatusChip status={r.status} /></dd>
                      <dt>Schedule</dt><dd>Checked every 15 minutes</dd>
                      <dt>Owner</dt><dd>{r.created_by}{r.run_id && <> (<a href={`/ask/?run=${r.run_id}`}>run</a>)</>}</dd>
                      <dt>Why</dt><dd className="ink-2">{r.rationale}</dd>
                    </dl>
                    {user?.role === "admin" && (
                      <div className="order__actions">
                        <button className="btn btn--sm" onClick={() => run(() => api(`/api/alerts/rules/${r.id}`, { method: "PATCH", json: { status: r.status === "active" ? "paused" : "active" } }), r.status === "active" ? "Rule paused." : "Rule resumed.")}>{r.status === "active" ? "Pause" : "Resume"}</button>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
        <aside className="briefing__margin">
          <section className="grid gap-2" aria-labelledby="raised-alerts">
            <h2 id="raised-alerts">Raised</h2>
            {events.isLoading && <Loading />}
            {events.error && <ErrorState error={events.error} retry={() => events.mutate()} />}
            {events.data?.events.length === 0 && <Empty title="No alerts have been raised">An alert appears when an active rule is breached for the latest complete month or quarter.</Empty>}
            {!!events.data?.events.length && (
              <ol className="log" aria-label="Dated log of triggered alerts">
                {events.data.events.map((e) => (
                  <li key={e.id}>
                    <time className="log__time" dateTime={e.created_at}>{when(e.created_at)}</time>
                    <span>{describe(e.rule)}</span>
                    <span className="log__figure">{e.period}: measured {metricValue(e.rule.metric, e.value)}</span>
                    <span>
                      {e.acknowledged ? <span className="chip">acknowledged</span> : user?.role !== "viewer" ? (
                        <button className="btn btn--sm" onClick={() => run(() => api(`/api/alerts/events/${e.id}/ack`, { method: "POST" }), "Acknowledged.")}>Acknowledge</button>
                      ) : <span className="chip chip--person">open</span>}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </aside>
      </div>
    </Page>
  );
}
