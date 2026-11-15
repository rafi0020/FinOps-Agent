"use client";

import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading } from "@/components/ui";
import { useApi } from "@/lib/api";
import { day, pct, usd } from "@/lib/format";

interface EvalRun {
  name: string; model: string; split: string; at: string; n: number;
  metrics: { answer_accuracy: number; overall_pass_rate?: number; root_cause_rate: number | null; behaviour_rate: number | null; unsupported_numbers_per_report: number; mean_steps: number; mean_cost_usd: number; p50_latency_s: number; p95_latency_s: number; completed_rate: number };
  by_kind: Record<string, { n: number; passed: number }>;
}
interface AttackRun { model: string; at: string; cases: { id: string; name: string; passed: boolean; detail: string }[] }

const setName = (r: { split: string }) => (r.split === "test" ? "held out" : "development");
const newest = <T extends { at: string }>(runs: T[]): T | undefined => runs.reduce<T | undefined>((best, r) => (!best || new Date(r.at) > new Date(best.at) ? r : best), undefined);

export default function EvaluationPage() {
  const { data, error, isLoading, mutate } = useApi<{ results: EvalRun[]; attacks: AttackRun[] }>("/api/eval/results");
  const latest = newest(data?.results ?? []);
  const latestAttack = newest(data?.attacks ?? []);
  return (
    <Page title="Evaluation" lede="How the agent scored on a fixed set of questions whose answers were computed independently, and whether it withstood a set of attacks. Results are shown as recorded, including failures.">
      {error && <ErrorState error={error} retry={() => mutate()} />}
      {isLoading && <Loading rows={6} />}
      {data && data.results.length === 0 && data.attacks.length === 0 && (
        <Empty title="No evaluation has been recorded on this installation">Run <span className="measured">python -m eval.run_eval --split dev --model &lt;model&gt;</span> in the backend to produce one. See docs/EVALUATION.md.</Empty>
      )}
      {latest && (
        <section className="scorecard" aria-label="Scorecard">
          <p className="briefing__lede">
            {latest.model} passed {pct(latest.metrics.overall_pass_rate ?? latest.metrics.answer_accuracy)} of the {latest.n} questions on the {setName(latest)} set, run {day(latest.at)}.
            {latestAttack && <> Against the attack suite it held {latestAttack.cases.filter((c) => c.passed).length} of {latestAttack.cases.length} attacks.</>}
          </p>
          <dl className="figures">
            <div><dt>Passed</dt><dd className="reading">{latest.metrics.overall_pass_rate == null ? "not scored" : pct(latest.metrics.overall_pass_rate)}</dd></div>
            <div><dt>Look-ups correct</dt><dd className="reading">{pct(latest.metrics.answer_accuracy)}</dd></div>
            <div><dt>Cause found</dt><dd className="reading">{latest.metrics.root_cause_rate == null ? "not scored" : pct(latest.metrics.root_cause_rate)}</dd></div>
            <div><dt>Right behaviour</dt><dd className="reading">{latest.metrics.behaviour_rate == null ? "not scored" : pct(latest.metrics.behaviour_rate)}</dd></div>
            <div><dt>Unsupported figures per report</dt><dd className="reading">{latest.metrics.unsupported_numbers_per_report.toFixed(2)}</dd></div>
          </dl>
        </section>
      )}
      {!!data?.results.length && (
        <section className="grid gap-2" aria-labelledby="question-sets">
          <h2 id="question-sets">Question sets</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Model</th><th>Set</th><th className="num">Questions</th><th className="num">Passed</th><th className="num">Look-ups correct</th><th className="num">Cause found</th><th className="num">Right behaviour</th><th className="num">Unsupported figures per report</th><th className="num">Steps</th><th className="num">Cost per question</th><th className="num">p50 / p95</th><th>Run on</th></tr></thead>
              <tbody>
                {data.results.map((r) => (
                  <tr key={r.name}>
                    <td className="measured">{r.model}</td><td>{setName(r)}</td><td className="num">{r.n}</td>
                    <td className="num">{r.metrics.overall_pass_rate == null ? "" : pct(r.metrics.overall_pass_rate)}</td><td className="num">{pct(r.metrics.answer_accuracy)}</td><td className="num">{r.metrics.root_cause_rate == null ? "" : pct(r.metrics.root_cause_rate)}</td>
                    <td className="num">{r.metrics.behaviour_rate == null ? "" : pct(r.metrics.behaviour_rate)}</td>
                    <td className="num">{r.metrics.unsupported_numbers_per_report.toFixed(2)}</td><td className="num">{r.metrics.mean_steps.toFixed(1)}</td>
                    <td className="num">{usd(r.metrics.mean_cost_usd)}</td><td className="num">{r.metrics.p50_latency_s.toFixed(0)} s / {r.metrics.p95_latency_s.toFixed(0)} s</td><td className="muted">{day(r.at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="label">Correct: the reported figure matched the reference within tolerance. Cause found: the planted cause was named. Right behaviour: asked for clarification or declined when that was the correct response.</p>
          <div className="kinds">
            {data.results.map((r) => (
              <section key={r.name} aria-label={`${r.model}, by kind of question`}>
                <h3>{r.model}</h3>
                <span className="label">{setName(r)}, by kind of question</span>
                <ul className="ruled">
                  {Object.entries(r.by_kind).map(([kind, v]) => (<li key={kind}><span>{kind.replace(/_/g, " ")}</span><span className="num">{v.passed} of {v.n}</span></li>))}
                </ul>
              </section>
            ))}
          </div>
        </section>
      )}
      {data?.attacks.map((a) => (
        <section key={a.model + a.at} className="grid gap-2">
          <h2>Attack suite, <span className="measured">{a.model}</span></h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Attack</th><th>Result</th><th>What happened</th></tr></thead>
              <tbody>
                {a.cases.map((c) => (<tr key={c.id}><td>{c.name}</td><td><span className={`chip ${c.passed ? "chip--ok" : "chip--bad"}`}>{c.passed ? "held" : "failed"}</span></td><td className="ink-2">{c.detail}</td></tr>))}
              </tbody>
            </table>
          </div>
          <p className="label">Run on {day(a.at)}.</p>
        </section>
      ))}
    </Page>
  );
}
