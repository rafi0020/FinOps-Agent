"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading, useToast } from "@/components/ui";
import { api, ApiError, useApi, useMe } from "@/lib/api";
import { day } from "@/lib/format";
import type { Investigation } from "@/lib/types";

/** Back issues: saved investigations grouped by the month they were saved in, newest month first. */
function byMonth(list: Investigation[]) {
  const groups = new Map<string, { key: string; label: string; items: Investigation[] }>();
  for (const inv of list) {
    const date = new Date(inv.created_at);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    const group = groups.get(key) ?? { key, label: date.toLocaleDateString(undefined, { year: "numeric", month: "long" }), items: [] };
    group.items.push(inv);
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => (a.key < b.key ? 1 : -1));
}

export default function InvestigationsPage() {
  const { user } = useMe();
  const router = useRouter();
  const toast = useToast();
  const [q, setQ] = useState("");
  const { data, error, isLoading, mutate } = useApi<{ investigations: Investigation[] }>(`/api/investigations?q=${encodeURIComponent(q)}`, { keepPreviousData: true });
  const canAct = user && user.role !== "viewer";
  const run = async (fn: () => Promise<unknown>, done: string) => {
    try { await fn(); toast(done); await mutate(); } catch (e) { toast(e instanceof ApiError ? e.message : "That did not work.", "bad"); }
  };
  const months = data ? byMonth(data.investigations) : [];
  return (
    <Page title="Investigations" lede="Answers people chose to keep. Open one to read it without running it again, or re-run it against current data.">
      {error && <ErrorState error={error} retry={() => mutate()} />}
      <div className="briefing">
        <div className="briefing__main">
          {isLoading && <Loading />}
          {data?.investigations.length === 0 && (
            <Empty title={q ? "No saved investigation matches" : "Nothing saved yet"}>
              {q ? "Try a shorter search." : "When a run finishes, use Save investigation to keep it here."}
              {canAct && !q && <a className="btn btn--primary" href="/ask/">Ask a question</a>}
            </Empty>
          )}
          {!!months.length && (
            <div className="issues">
              {months.map((month) => (
                <section className="issues__month" key={month.key} aria-label={month.label}>
                  <h2>{month.label}</h2>
                  {month.items.map((inv) => {
                    const mine = user?.role === "admin" || user?.id === inv.created_by_id;
                    return (
                      <article className="issue" key={inv.id}>
                        <h3 className="issue__title"><a href={`/ask/?run=${inv.run_id}`}>{inv.question}</a></h3>
                        {inv.summary && <p className="issue__standfirst">{inv.summary}</p>}
                        <p className="issue__meta">
                          <time dateTime={inv.created_at}>{day(inv.created_at)}</time>
                          <span>Filed as {inv.title}</span>
                          <span>Saved by {inv.created_by ?? "a deleted user"}</span>
                          {inv.pinned && <span className="chip chip--person">pinned</span>}
                        </p>
                        {canAct && (
                          <div className="issue__actions">
                            <button className="btn btn--sm" onClick={async () => { try { const r = await api<{ id: string }>(`/api/investigations/${inv.id}/rerun`, { method: "POST" }); router.push(`/ask/?run=${r.id}`); } catch (e) { toast(e instanceof ApiError ? e.message : "Could not re-run.", "bad"); } }}>Re-run</button>
                            {mine && <button className="btn btn--sm" onClick={() => run(() => api(`/api/investigations/${inv.id}`, { method: "PATCH", json: { pinned: !inv.pinned } }), inv.pinned ? "Unpinned." : "Pinned.")}>{inv.pinned ? "Unpin" : "Pin"}</button>}
                            {mine && <button className="btn btn--sm btn--danger" onClick={() => { if (confirm(`Delete "${inv.title}"? The run itself is kept.`)) void run(() => api(`/api/investigations/${inv.id}`, { method: "DELETE" }), "Deleted."); }}>Delete</button>}
                          </div>
                        )}
                      </article>
                    );
                  })}
                </section>
              ))}
            </div>
          )}
        </div>
        <aside className="briefing__margin">
          <div className="margin-search">
            <label className="field">
              <span className="label">Search titles and questions</span>
              <input className="input" type="search" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
            {data && <p className="hint">{data.investigations.length} {data.investigations.length === 1 ? "investigation" : "investigations"}{q ? " match" : " saved"}.</p>}
          </div>
        </aside>
      </div>
    </Page>
  );
}
