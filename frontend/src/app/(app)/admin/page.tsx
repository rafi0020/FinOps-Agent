"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading, StatusChip, useToast } from "@/components/ui";
import { api, ApiError, useApi, useMe } from "@/lib/api";
import { when } from "@/lib/format";
import type { Role } from "@/lib/types";

interface Member { id: string; email: string; name: string; role: Role; is_active: boolean; created_at: string }
interface LLM { provider: string; model: string; base_url: string; fallback_model: string; price_input_per_mtok: number; price_output_per_mtok: number; api_key_set: boolean; source: string }
interface AuditEntry { id: number; at: string; user: string | null; action: string; target: string | null; detail: Record<string, unknown> | null; ip: string | null }
const TABS = [["users", "People"], ["model", "Model"], ["audit", "Audit log"]] as const;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "That did not work.");

function Users() {
  const { user: me } = useMe();
  const toast = useToast();
  const { data, error, isLoading, mutate } = useApi<{ users: Member[] }>("/api/users");
  const [form, setForm] = useState({ email: "", name: "", role: "analyst" as Role, password: "" });
  const [problem, setProblem] = useState("");
  const patch = async (id: string, json: Partial<Member>, done: string) => {
    try { await api(`/api/users/${id}`, { method: "PATCH", json }); toast(done); } catch (e) { toast(message(e), "bad"); }
    await mutate();
  };
  const add = async (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    try {
      await api("/api/users", { method: "POST", json: form });
      toast(`${form.email} can now sign in.`);
      setForm({ email: "", name: "", role: "analyst", password: "" });
      await mutate();
    } catch (e) { setProblem(message(e)); }
  };
  return (
    <>
      <section className="setting" aria-labelledby="people-heading">
        <div className="setting__label">
          <h2 id="people-heading">People</h2>
          {data && <span className="hint">{data.users.length} {data.users.length === 1 ? "account" : "accounts"}</span>}
        </div>
        <div className="setting__controls">
          {isLoading && <Loading />}
          {error && <ErrorState error={error} retry={() => mutate()} />}
          {data && (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Person</th><th>Role</th><th>Status</th><th>Added</th><th /></tr></thead>
                <tbody>
                  {data.users.map((u) => (
                    <tr key={u.id}>
                      <td>{u.name}<div className="label measured">{u.email}</div></td>
                      <td>
                        <select className="select" aria-label={`Role of ${u.email}`} value={u.role} onChange={(e) => patch(u.id, { role: e.target.value as Role }, `${u.email} is now ${e.target.value}.`)}>
                          <option value="viewer">viewer</option><option value="analyst">analyst</option><option value="admin">admin</option>
                        </select>
                      </td>
                      <td><StatusChip status={u.is_active ? "active" : "rejected"} label={u.is_active ? "active" : "deactivated"} /></td>
                      <td className="muted">{when(u.created_at)}</td>
                      <td>
                        {u.id !== me?.id && <button className={`btn btn--sm ${u.is_active ? "btn--danger" : ""}`} onClick={() => patch(u.id, { is_active: !u.is_active }, u.is_active ? `${u.email} was signed out and deactivated.` : `${u.email} can sign in again.`)}>{u.is_active ? "Deactivate" : "Reactivate"}</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="setting__note">
          <p>Roles decide what a person may do. A viewer reads saved results. An analyst also asks the agent questions. An administrator also approves proposed actions and manages people and settings.</p>
          <p>A change of role applies at once. Deactivating someone signs them out.</p>
        </div>
      </section>
      <section className="setting" aria-labelledby="add-person-heading">
        <div className="setting__label"><h2 id="add-person-heading">Add a person</h2></div>
        <form className="setting__controls setting__form" onSubmit={add}>
          <div className="setting__fields">
            <label className="field"><span className="label">Name</span><input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label className="field"><span className="label">E-mail</span><input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
            <label className="field"><span className="label">Role</span>
              <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                <option value="viewer">viewer: reads</option><option value="analyst">analyst: asks the agent</option><option value="admin">admin: approves and manages</option>
              </select>
            </label>
            <label className="field"><span className="label">Initial password</span><input className="input" type="password" required autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /><span className="hint">At least 10 characters, with a letter and a number.</span></label>
          </div>
          {problem && <p className="hint hint--bad" role="alert">{problem}</p>}
          <div className="setting__actions"><button className="btn btn--primary">Add person</button></div>
        </form>
        <div className="setting__note">
          <p>The new person signs in with this e-mail address and password. Their role can be changed in the list above at any time.</p>
        </div>
      </section>
    </>
  );
}

function Model() {
  const toast = useToast();
  const { data, error, isLoading, mutate } = useApi<LLM>("/api/settings/llm");
  const [form, setForm] = useState<LLM | null>(null);
  const [key, setKey] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setForm(data); }, [data]);
  if (isLoading || !form) return error ? <ErrorState error={error} retry={() => mutate()} /> : <Loading />;
  const set = <K extends keyof LLM>(k: K, v: LLM[K]) => setForm({ ...form, [k]: v });
  const save = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const body = { ...form, api_key: key ? key : undefined };
      await mutate(await api<LLM>("/api/settings/llm", { method: "PUT", json: body }), false);
      setKey("");
      toast("Model settings saved.");
    } catch (e) { toast(message(e), "bad"); }
  };
  const test = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await api<{ ok: boolean; error?: string; model?: string; latency_ms?: number }>("/api/settings/llm/test", { method: "POST" });
      setResult(r.ok ? { ok: true, text: `Connected to ${r.model} in ${r.latency_ms} ms.` } : { ok: false, text: r.error ?? "The test failed." });
    } catch (e) { setResult({ ok: false, text: message(e) }); }
    setBusy(false);
  };
  return (
    <section className="setting" aria-labelledby="model-heading">
      <div className="setting__label">
        <h2 id="model-heading">Provider and model</h2>
        <span className="chip">{form.source === "organisation" ? "set for this organisation" : "using the server default"}</span>
      </div>
      <form className="setting__controls setting__form" onSubmit={save}>
        <div className="setting__fields">
          <label className="field"><span className="label">Provider</span>
            <select className="select" value={form.provider} onChange={(e) => set("provider", e.target.value)}>
              <option value="openai_compat">OpenAI-compatible (OpenAI, Gemini, Groq, 9Router, any gateway)</option>
              <option value="anthropic">Anthropic</option><option value="ollama">Ollama (local)</option><option value="stub">Built-in demonstration script (no model)</option>
            </select>
          </label>
          <label className="field"><span className="label">Model</span><input className="input measured" required value={form.model} onChange={(e) => set("model", e.target.value)} /></label>
          <label className="field wide"><span className="label">Base URL</span><input className="input measured" value={form.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder={form.provider === "ollama" ? "http://host.docker.internal:11434/v1" : "https://api.example.com/v1"} /></label>
          <label className="field"><span className="label">Fallback model (optional)</span><input className="input measured" value={form.fallback_model} onChange={(e) => set("fallback_model", e.target.value)} /></label>
          <label className="field"><span className="label">API key</span>
            <input className="input measured" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={form.api_key_set ? "A key is stored. Type a new one to replace it." : "No key stored"} />
            <span className="hint">Stored encrypted. It is never shown again and never sent to the browser.</span>
          </label>
          <label className="field"><span className="label">Price per million input tokens, USD</span><input className="input measured" type="number" min={0} step="0.01" value={form.price_input_per_mtok} onChange={(e) => set("price_input_per_mtok", Number(e.target.value))} /></label>
          <label className="field"><span className="label">Price per million output tokens, USD</span><input className="input measured" type="number" min={0} step="0.01" value={form.price_output_per_mtok} onChange={(e) => set("price_output_per_mtok", Number(e.target.value))} /></label>
        </div>
        <div className="setting__actions">
          <button className="btn btn--primary">Save</button>
          <button type="button" className="btn" onClick={test} disabled={busy} aria-busy={busy}>Test the saved settings</button>
          {result && <span className={result.ok ? "ok" : "bad"} role="status">{result.text}</span>}
        </div>
      </form>
      <div className="setting__note">
        <p>Prices are used to estimate cost and enforce budgets. Set them to what your provider charges.</p>
        <p>The test uses the saved settings, so save first.</p>
      </div>
    </section>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const [before, setBefore] = useState<number | null>(null);
  const { data, error, isLoading, mutate } = useApi<{ entries: AuditEntry[]; next_before: number | null }>(`/api/audit?limit=50&action=${encodeURIComponent(action)}${before ? `&before=${before}` : ""}`, { keepPreviousData: true });
  return (
    <section className="setting" aria-labelledby="record-heading">
      <div className="setting__label"><h2 id="record-heading">Record</h2></div>
      <div className="setting__controls">
        <div className="setting__actions">
          <select className="select max-w-xs" value={action} onChange={(e) => { setAction(e.target.value); setBefore(null); }} aria-label="Filter by kind">
            <option value="">Everything</option><option value="auth.">Sign-ins</option><option value="user.">People</option><option value="run.">Runs</option>
            <option value="approval.">Approvals</option><option value="alert.">Alerts</option><option value="settings.">Settings</option><option value="investigation.">Investigations</option>
          </select>
          {before && <button className="btn" onClick={() => setBefore(null)}>Back to newest</button>}
        </div>
        {isLoading && !data && <Loading />}
        {error && <ErrorState error={error} retry={() => mutate()} />}
        {data?.entries.length === 0 && <Empty title="No entries">Nothing of this kind has been recorded.</Empty>}
        {!!data?.entries.length && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th><th>Address</th></tr></thead>
              <tbody>
                {data.entries.map((e) => (
                  <tr key={e.id}>
                    <td className="muted measured">{when(e.at)}</td><td>{e.user ?? "deleted user"}</td><td className="measured">{e.action}</td>
                    <td className="ink-2 measured">{e.detail ? JSON.stringify(e.detail).slice(0, 160) : ""}</td><td className="muted measured">{e.ip}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data?.next_before && <div><button className="btn" onClick={() => setBefore(data.next_before)}>Older entries</button></div>}
      </div>
      <div className="setting__note">
        <p>Newest first. Filter by kind to see only sign-ins, changes to people, runs, approvals, alerts, settings or investigations.</p>
        <p>The address column shows where each request came from.</p>
      </div>
    </section>
  );
}

function AdminPage() {
  const router = useRouter();
  const tab = useSearchParams().get("tab") ?? "users";
  const { user } = useMe();
  if (user && user.role !== "admin") return <Page title="Administration"><Empty title="Administrators only">Ask an administrator of your organisation for access.</Empty></Page>;
  return (
    <Page title="Administration" lede="People and roles, the model the agent uses, and the record of who did what.">
      <div className="tabs" role="tablist">
        {TABS.map(([value, label]) => (<button key={value} className="tab" role="tab" aria-selected={tab === value} onClick={() => router.replace(`/admin/?tab=${value}`)}>{label}</button>))}
      </div>
      <div className="settings">
        {tab === "users" && <Users />}
        {tab === "model" && <Model />}
        {tab === "audit" && <Audit />}
      </div>
    </Page>
  );
}

export default function AdminRoute() {
  return (<Suspense fallback={<Loading />}><AdminPage /></Suspense>);
}
