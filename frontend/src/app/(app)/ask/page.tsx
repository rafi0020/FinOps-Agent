"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { EvidenceDrawer } from "@/components/Evidence";
import { ReportMargin, ReportView } from "@/components/ReportView";
import { RunTrail } from "@/components/RunTrail";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading, StatusChip, useToast } from "@/components/ui";
import { api, ApiError, useApi, useMe } from "@/lib/api";
import { STATUS_LABEL, usd, when } from "@/lib/format";
import { followRun } from "@/lib/sse";
import type { Run } from "@/lib/types";

const EXAMPLES = [
  "Why did gross margin fall in the West region in Q3 2026?",
  "Which customer segment had the biggest change in discount rate in Q2 2026?",
  "What was revenue by region in Q3 2026 compared with Q2?",
  "Alert me if West gross margin drops below 25% in a quarter.",
];
const ACTIVE = ["queued", "running"];
const FINAL = ["completed", "failed", "cancelled", "budget_exceeded"];

function AskForm() {
  const router = useRouter();
  const toast = useToast();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const runs = useApi<{ runs: Run[] }>("/api/runs?limit=15");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (question.trim().length < 3) return;
    setBusy(true);
    try {
      const { id } = await api<{ id: string }>("/api/runs", { method: "POST", json: { question } });
      router.push(`/ask/?run=${id}`);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Could not start the run.", "bad");
      setBusy(false);
    }
  }

  return (
    <Page title="Ask" lede="Ask a question about sales, margin, costs, expenses or collections. The agent shows each step it takes and links every figure to its query.">
      <form className="panel" onSubmit={submit}>
        <div className="panel__body grid gap-3">
          <label className="field">
            <span className="label">Your question</span>
            <textarea className="textarea" rows={3} maxLength={2000} value={question} onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit(); }}
              placeholder="For example: why did operating margin fall last quarter?" />
          </label>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="hint">Data covers January 2024 to September 2026. Ctrl + Enter to send.</span>
            <button className="btn btn--primary" disabled={busy || question.trim().length < 3} aria-busy={busy}>Ask the agent</button>
          </div>
        </div>
      </form>
      <section className="grid gap-2">
        <h2>Try one of these</h2>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((q) => (<button key={q} className="btn" onClick={() => setQuestion(q)}>{q}</button>))}
        </div>
      </section>
      <section className="grid gap-2">
        <h2>Recent questions</h2>
        <div className="panel table-wrap">
          {runs.isLoading && <Loading />}
          {runs.error && <div className="p-4"><ErrorState error={runs.error} retry={() => runs.mutate()} /></div>}
          {runs.data?.runs.length === 0 && <Empty title="No questions yet">Ask one above; it will appear here with its result.</Empty>}
          {!!runs.data?.runs.length && (
            <table className="table">
              <thead><tr><th>Question</th><th>Asked by</th><th>When</th><th>Status</th><th className="num">Est. cost</th></tr></thead>
              <tbody>
                {runs.data.runs.map((r) => (
                  <tr key={r.id}>
                    <td><a href={`/ask/?run=${r.id}`}>{r.question}</a></td>
                    <td className="muted">{r.asked_by}</td>
                    <td className="muted">{when(r.created_at)}</td>
                    <td><StatusChip status={r.status} label={STATUS_LABEL[r.status]} /></td>
                    <td className="num">{usd(r.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </Page>
  );
}

function RunView({ id }: { id: string }) {
  const { user } = useMe();
  const toast = useToast();
  const { data: run, error, mutate } = useApi<Run>(`/api/runs/${id}`);
  const [evidence, setEvidence] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [title, setTitle] = useState("");
  const [saved, setSaved] = useState(false);
  const live = run ? ACTIVE.includes(run.status) : false;
  // A run waiting for an answer or an approval is not finished: keep listening, so the page moves on by
  // itself when someone else (an administrator approving, say) lets it continue.
  const unfinished = run ? !FINAL.includes(run.status) : false;

  // Until the run is finished, every event from the server refreshes it. Reconnection is automatic.
  useEffect(() => (unfinished ? followRun(id, () => void mutate()) : undefined), [id, unfinished, mutate]);

  if (error) return <Page title="Run"><ErrorState error={error} retry={() => mutate()} /></Page>;
  if (!run) return <Page title="Run"><Loading rows={8} /></Page>;
  const mine = user?.role === "admin" || user?.id === run.user_id;
  const act = async (path: string, json: unknown, done: string) => {
    try {
      await api(path, { method: "POST", json });
      toast(done);
      await mutate();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "That did not work.", "bad");
    }
  };

  return (
    <Page
      title={run.question}
      actions={
        <>
          <StatusChip status={run.status} label={STATUS_LABEL[run.status]} />
          {mine && (live || run.status.startsWith("waiting")) && <button className="btn btn--danger" onClick={() => act(`/api/runs/${id}/cancel`, undefined, "Cancelling the run.")}>Cancel</button>}
          <a className="btn" href="/ask/">New question</a>
        </>
      }
    >
      {run.status === "waiting_user" && (
        <form className="banner banner--person" onSubmit={(e) => { e.preventDefault(); void act(`/api/runs/${id}/answer`, { text: answer }, "Answer sent; the agent is continuing."); setAnswer(""); }}>
          <div className="grid gap-2 w-full">
            <strong>The agent needs one thing from you: {run.pending?.question}</strong>
            {mine ? (
              <div className="flex gap-2">
                <input className="input" value={answer} onChange={(e) => setAnswer(e.target.value)} maxLength={1000} aria-label="Your answer" autoFocus />
                <button className="btn btn--primary" disabled={!answer.trim()}>Send answer</button>
              </div>
            ) : <span>Only the person who asked, or an administrator, can answer.</span>}
          </div>
        </form>
      )}
      {run.status === "waiting_approval" && (
        <div className="banner banner--person">
          <span>The agent proposed an action ({run.pending?.tool?.replace(/_/g, " ")}) that needs an administrator&apos;s approval. Nothing has been changed.</span>
          <a className="btn" href="/approvals/">Open approvals</a>
        </div>
      )}
      {run.error && <div className="banner banner--bad" role="alert">{run.error}</div>}

      <div className="briefing">
        <div className="briefing__main">
          {run.report ? <ReportView report={run.report} onEvidence={setEvidence} /> : (
            <div className="panel">
              {live ? <Loading rows={5} label="The agent is working" /> : unfinished ? <Empty title="Paused">The report will appear here once the run continues.</Empty> : <Empty title="No report">{run.status === "cancelled" ? "This run was cancelled before it finished." : "The run ended without a report. The trail shows how far it got."}</Empty>}
            </div>
          )}
          {run.status === "completed" && user?.role !== "viewer" && !saved && (
            <form className="flex flex-wrap gap-2" onSubmit={async (e) => { e.preventDefault(); try { await api("/api/investigations", { method: "POST", json: { run_id: id, title: title || run.question.slice(0, 150) } }); setSaved(true); toast("Saved to Investigations."); } catch (err) { toast(err instanceof ApiError ? err.message : "Could not save.", "bad"); if (err instanceof ApiError && err.status === 409) setSaved(true); } }}>
              <input className="input max-w-md" placeholder="Title for the saved investigation" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} aria-label="Investigation title" />
              <button className="btn">Save investigation</button>
            </form>
          )}
        </div>
        <aside className="briefing__margin">
          {run.report && <ReportMargin report={run.report} onEvidence={setEvidence} />}
          <section className="panel">
            <div className="panel__head"><h2>Trail</h2><span className="label measured">{run.steps_used} model steps, {run.tokens_used.toLocaleString()} tokens, est. {usd(run.cost_usd)}</span></div>
            <div className="panel__body"><RunTrail run={run} onEvidence={setEvidence} /></div>
          </section>
        </aside>
      </div>
      {evidence && <EvidenceDrawer runId={id} handle={evidence} onClose={() => setEvidence(null)} />}
    </Page>
  );
}

function AskPage() {
  const run = useSearchParams().get("run");
  return run ? <RunView key={run} id={run} /> : <AskForm />;
}

export default function Ask() {
  return (
    <Suspense fallback={<Loading />}>
      <AskPage />
    </Suspense>
  );
}
