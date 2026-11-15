"use client";

import { Fragment, useState } from "react";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading, StatusChip, useToast } from "@/components/ui";
import { api, ApiError, useApi, useMe } from "@/lib/api";
import { METRIC_LABEL, metricValue, when } from "@/lib/format";
import type { Approval } from "@/lib/types";

/** The proposed action as one sentence. Alert rules get their condition spelled out; other tools fall back to their name. */
function proposal(a: Approval): string {
  const args = a.arguments;
  if (a.tool === "propose_alert") {
    const metric = String(args.metric ?? "");
    const label = (METRIC_LABEL[metric] ?? metric).toLowerCase();
    const value = typeof args.threshold === "number" ? metricValue(metric, args.threshold) : String(args.threshold ?? "");
    const region = args.region ? ` in ${String(args.region)}` : "";
    return `Raise an alert when ${label}${region} is ${args.comparison === "<" ? "below" : "above"} ${value}, per ${String(args.window ?? "period")}.`;
  }
  const name = a.tool.replace(/_/g, " ");
  return `${name.charAt(0).toUpperCase()}${name.slice(1)}.`;
}

export default function ApprovalsPage() {
  const { user } = useMe();
  const toast = useToast();
  const [tab, setTab] = useState<"pending" | "all">("pending");
  const [reason, setReason] = useState<Record<string, string>>({});
  const { data, error, isLoading, mutate } = useApi<{ approvals: Approval[] }>(`/api/approvals?status=${tab}`);
  const admin = user?.role === "admin";
  const decide = async (a: Approval, decision: "approved" | "rejected") => {
    try {
      await api(`/api/approvals/${a.id}/decide`, { method: "POST", json: { decision, reason: reason[a.id] || null } });
      toast(decision === "approved" ? "Approved. The agent will carry it out." : "Rejected. The agent has been told.");
      await mutate();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "That did not work.", "bad");
      await mutate();
    }
  };
  const items = data?.approvals ?? [];
  const waiting = items.filter((a) => a.status === "pending");
  const decided = items.filter((a) => a.status !== "pending");
  return (
    <Page title="Approvals" lede={admin ? "Actions the agent has proposed. Nothing happens until you decide." : "Actions you asked the agent to take that are waiting for an administrator."}>
      <div className="tabs" role="tablist">
        <button className="tab" role="tab" aria-selected={tab === "pending"} onClick={() => setTab("pending")}>Waiting</button>
        <button className="tab" role="tab" aria-selected={tab === "all"} onClick={() => setTab("all")}>All decisions</button>
      </div>
      {error && <ErrorState error={error} retry={() => mutate()} />}
      {isLoading && <Loading />}
      {data?.approvals.length === 0 && <Empty title={tab === "pending" ? "Nothing is waiting" : "No decisions have been made yet"}>Requests appear here when the agent proposes an action such as creating an alert rule.</Empty>}
      {!!waiting.length && (
        <section className="grid gap-2" aria-label="Waiting for a decision">
          {tab === "all" && <h2>Waiting</h2>}
          <div className="docket">
            {waiting.map((a) => (
              <article key={a.id} className="docket__item">
                <div className="grid gap-3 min-w-0">
                  <h2 className="docket__sentence">{proposal(a)}</h2>
                  <p className="docket__request"><span className="person">{a.requested_by ?? "Someone"}</span> <span className="muted">asked on {when(a.created_at)}:</span> <a href={`/ask/?run=${a.run_id}`}>{a.question}</a></p>
                  <dl className="facts">
                    {Object.entries(a.arguments).map(([k, v]) => (
                      <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd className="measured">{v == null ? "whole company" : String(v)}</dd></Fragment>
                    ))}
                  </dl>
                </div>
                <div className="docket__margin">
                  <StatusChip status={a.status} />
                  {admin && (
                    <>
                      <label className="field">
                        <span className="label">Reason (optional)</span>
                        <input className="input" placeholder="Shown to the agent if rejected" maxLength={500} value={reason[a.id] ?? ""} onChange={(e) => setReason({ ...reason, [a.id]: e.target.value })} />
                      </label>
                      <div className="docket__buttons">
                        <button className="btn btn--primary" onClick={() => decide(a, "approved")}>Approve</button>
                        <button className="btn btn--danger" onClick={() => decide(a, "rejected")}>Reject</button>
                      </div>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
      {tab === "all" && !!decided.length && (
        <section className="grid gap-2" aria-label="Decided">
          <h2>Decided</h2>
          <ol className="record">
            {decided.map((a) => (
              <li key={a.id}>
                <div className="record__head">
                  <span className="record__sentence">{proposal(a)}</span>
                  <StatusChip status={a.status} />
                </div>
                <p className="muted">
                  Asked by {a.requested_by ?? "someone"} on {when(a.created_at)}
                  {a.decided_at && <>, decided {when(a.decided_at)}</>}. <a href={`/ask/?run=${a.run_id}`}>{a.question}</a>
                </p>
                {a.reason && <p className="ink-2">Reason given: {a.reason}</p>}
              </li>
            ))}
          </ol>
        </section>
      )}
    </Page>
  );
}
