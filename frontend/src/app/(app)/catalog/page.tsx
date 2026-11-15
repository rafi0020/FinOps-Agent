"use client";

import { useState } from "react";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading } from "@/components/ui";
import { useApi } from "@/lib/api";

interface Catalog {
  tables: { name: string; description: string; columns: { name: string; type: string; description: string }[] }[];
  metrics: { name: string; definition: string; sql: string }[];
  data_range: { first_order: string; last_order: string; reporting_currency: string };
}

const anchor = (name: string) => `table-${name}`;

export default function CatalogPage() {
  const { data, error, isLoading, mutate } = useApi<Catalog>("/api/catalog");
  const [filter, setFilter] = useState("");
  const term = filter.trim().toLowerCase();
  const tables = (data?.tables.filter((t) => !term || t.name.includes(term) || t.columns.some((c) => c.name.includes(term) || c.description.toLowerCase().includes(term))) ?? [])
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));
  return (
    <Page title="Data catalogue" lede="The tables and definitions the agent is given. It can read these views for your organisation and nothing else.">
      {error && <ErrorState error={error} retry={() => mutate()} />}
      {isLoading && <Loading rows={8} />}
      {data && (
        <div className="briefing">
          <div className="briefing__main">
            <section className="grid gap-4" aria-labelledby="metric-definitions">
              <h2 id="metric-definitions">Metric definitions</h2>
              <dl className="glossary">
                {data.metrics.map((m) => (
                  <div key={m.name}>
                    <dt>{m.name.replace(/_/g, " ")}</dt>
                    <dd>{m.definition}</dd>
                    <dd className="glossary__calc">{m.sql}</dd>
                  </div>
                ))}
              </dl>
              <p className="label">Data covers {data.data_range.first_order} to {data.data_range.last_order}. Reporting currency: {data.data_range.reporting_currency}.</p>
            </section>
            <section className="grid gap-4" aria-labelledby="schema-tables">
              <h2 id="schema-tables">Tables in schema analytics</h2>
              {tables.length === 0 && <Empty title="Nothing matches that filter">Clear the filter to see every table.</Empty>}
              <div className="entries">
                {tables.map((t) => (
                  <section key={t.name} id={anchor(t.name)} className="entry" aria-labelledby={`${anchor(t.name)}-name`}>
                    <h3 className="entry__name" id={`${anchor(t.name)}-name`}>{t.name}</h3>
                    <p className="entry__desc">{t.description}</p>
                    <p className="entry__meta">{t.columns.length} columns</p>
                    <ul className="columns" aria-label={`Columns of ${t.name}`}>
                      {t.columns.map((c) => (
                        <li key={c.name}>
                          <span className="columns__name">{c.name}</span>
                          <span className="columns__type">{c.type}</span>
                          <span className="columns__meaning">{c.description}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            </section>
          </div>
          <aside className="briefing__margin">
            <div className="margin-search">
              <label className="field">
                <span className="label">Filter tables and columns</span>
                <input className="input" type="search" placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
              </label>
            </div>
            <nav aria-label="Index of tables" className="grid gap-2 content-start">
              <h2>Index</h2>
              {tables.length === 0 ? <p className="hint">No table matches.</p> : (
                <ul className="index">
                  {tables.map((t) => (
                    <li key={t.name}><a href={`#${anchor(t.name)}`}>{t.name}<span className="index__count">{t.columns.length}</span></a></li>
                  ))}
                </ul>
              )}
            </nav>
          </aside>
        </div>
      )}
    </Page>
  );
}
