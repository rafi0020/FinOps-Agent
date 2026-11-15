"use client";

import { Fragment, type ReactNode } from "react";
import type { NumberRef, Report } from "@/lib/types";
import { Chart } from "./Chart";

/** Footnote numbers in the order a reader meets each evidence handle: the answer's figures, then findings, then the list. */
function footnotes(report: Report): Map<string, number> {
  const order = new Map<string, number>();
  const add = (handle?: string | null) => { if (handle && !order.has(handle)) order.set(handle, order.size + 1); };
  report.summary_numbers.forEach((r) => add(r.handle));
  report.findings.forEach((f) => { f.numbers.forEach((r) => add(r.handle)); f.evidence.forEach(add); });
  report.charts.forEach((c) => add(c.handle));
  report.evidence.forEach((e) => add(e.handle));
  return order;
}

/** Turn each supported figure in the text into a control that opens the evidence it came from, with its footnote number. */
function linkFigures(text: string, refs: NumberRef[], open: (handle: string) => void, notes: Map<string, number>): ReactNode[] {
  const out: ReactNode[] = [];
  let cursor = 0;
  refs.forEach((ref, i) => {
    const at = text.indexOf(ref.text, cursor);
    if (at < 0) return;
    out.push(<Fragment key={`t${i}`}>{text.slice(cursor, at)}</Fragment>);
    const n = notes.get(ref.handle);
    out.push(
      <button key={`f${i}`} className="fig" title={`Open evidence ${ref.handle}`} onClick={() => open(ref.handle)}>
        {ref.text}{n != null && <sup className="fn">{n}</sup>}
      </button>,
    );
    cursor = at + ref.text.length;
  });
  out.push(<Fragment key="rest">{text.slice(cursor)}</Fragment>);
  return out;
}

/** The answer, read as a briefing: standfirst, numbered findings, removed statements, recommendations and the evidence list. */
export function ReportView({ report, onEvidence }: { report: Report; onEvidence: (handle: string) => void }) {
  const notes = footnotes(report);
  return (
    <>
      <section className="grid gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2>{report.outcome === "cannot_answer" ? "The agent could not answer this" : "Answer"}</h2>
          {report.outcome === "answered" && report.unsupported.length === 0 && <span className="chip chip--ok">every figure traced</span>}
        </div>
        <p className="briefing__lede">{report.summary ? linkFigures(report.summary, report.summary_numbers, onEvidence, notes) : "No supported statement remained in the summary."}</p>
      </section>

      {report.unsupported.length > 0 && (
        <section className="banner banner--bad" aria-label="Removed statements">
          <div className="grid gap-1">
            <strong>{report.unsupported.length} statement{report.unsupported.length > 1 ? "s were" : " was"} removed</strong>
            <span>The agent wrote {report.unsupported.length > 1 ? "these" : "this"}, but a figure in {report.unsupported.length > 1 ? "them" : "it"} could not be found in the evidence:</span>
            <ul className="m-0 pl-5">{report.unsupported.map((s) => (<li key={s}>{s}</li>))}</ul>
          </div>
        </section>
      )}

      {report.findings.length > 0 && (
        <section className="grid gap-2">
          <h2>Findings</h2>
          <ol className="findings">
            {report.findings.map((f) => (
              <li key={f.number} className="finding">
                <span className="finding__no" aria-hidden>{f.number}</span>
                <div className="finding__body">
                  <p className="prose">{linkFigures(f.claim, f.numbers, onEvidence, notes)}</p>
                  <div className="based-on">
                    <span className="label">Based on</span>
                    {f.evidence.map((h) => (<button key={h} className="fig" onClick={() => onEvidence(h)}>{h}{notes.get(h) != null && <sup className="fn">{notes.get(h)}</sup>}</button>))}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      {report.recommendations.length > 0 && (
        <section className="grid gap-2">
          <h2>Recommendations</h2>
          <ul className="prose m-0 pl-5">{report.recommendations.map((r) => (<li key={r}>{r}</li>))}</ul>
          <p className="label">Recommendations are the agent&apos;s suggestions. They are not checked against the evidence.</p>
        </section>
      )}

      {report.evidence.length > 0 && (
        <section className="grid gap-2">
          <h2>Evidence</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th className="num">No.</th><th>Handle</th><th>Kind</th><th>What it is</th><th className="num">Rows</th></tr></thead>
              <tbody>
                {report.evidence.map((e) => (
                  <tr key={e.handle}>
                    <td className="num">{notes.get(e.handle) ?? ""}</td>
                    <td><button className="fig" onClick={() => onEvidence(e.handle)}>{e.handle}</button></td>
                    <td>{e.kind}</td>
                    <td className="ink-2">{e.purpose ?? ""}</td>
                    <td className="num">{e.kind === "chart" ? "" : e.row_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

/** The figures of the answer, set in the margin beside the text they support. */
export function ReportMargin({ report, onEvidence }: { report: Report; onEvidence: (handle: string) => void }) {
  if (report.charts.length === 0) return null;
  return (
    <>
      {report.charts.map((chart) => (
        <section key={chart.chart_handle ?? chart.title} className="margin-note">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3>{chart.title}</h3>
            {chart.handle && <button className="fig" onClick={() => onEvidence(chart.handle!)}>{chart.handle}</button>}
          </div>
          <Chart spec={chart} />
        </section>
      ))}
    </>
  );
}
