"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api, ApiError, BASE, setCsrf } from "@/lib/api";

const DEMO = [
  ["Analyst", "analyst@northwind.demo", "Analyst#Demo2026"],
  ["Administrator", "admin@northwind.demo", "Admin#Demo2026"],
  ["Viewer", "viewer@northwind.demo", "Viewer#Demo2026"],
];

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const [form, setForm] = useState({ email: "", password: "", name: "", org_name: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = mode === "login" ? { email: form.email, password: form.password } : form;
      const result = await api<{ csrf_token: string }>(`/api/auth/${mode}`, { method: "POST", json: body });
      setCsrf(result.csrf_token);
      window.location.href = `${BASE}/overview/`;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <header className="auth__masthead">
        <h1 className="auth__title">FinOps Agent</h1>
      </header>
      <div className="auth__cols">
        <div className="auth__form">
          <h2>{mode === "login" ? "Sign in" : "Create your organisation"}</h2>
          <form onSubmit={submit} noValidate>
            {mode === "signup" && (
              <>
                <label className="field"><span className="label">Organisation name</span><input className="input" required value={form.org_name} onChange={set("org_name")} autoComplete="organization" /></label>
                <label className="field"><span className="label">Your name</span><input className="input" required value={form.name} onChange={set("name")} autoComplete="name" /></label>
              </>
            )}
            <label className="field"><span className="label">E-mail</span><input className="input" type="email" required value={form.email} onChange={set("email")} autoComplete="email" aria-invalid={!!error} /></label>
            <label className="field">
              <span className="label">Password</span>
              <input className="input" type="password" required value={form.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} aria-invalid={!!error} />
              {mode === "signup" && <span className="hint">At least 10 characters, with a letter and a number.</span>}
            </label>
            {error && <p className="hint hint--bad" role="alert">{error}</p>}
            <button className="btn btn--primary" disabled={busy} aria-busy={busy}>{mode === "login" ? "Sign in" : "Create organisation"}</button>
          </form>
          <p className="muted">
            {mode === "login" ? <>New here? <Link href="/signup/">Create an organisation</Link></> : <>Already have an account? <Link href="/login/">Sign in</Link></>}
          </p>
        </div>
        <aside className="auth__column">
          <p className="auth__standfirst">Every figure links to the query behind it.</p>
          <p className="auth__body">Ask a finance question in plain English. The agent queries the data, calculates with fixed functions, and removes any number it cannot trace.</p>
          {mode === "login" && (
            <section className="panel">
              <div className="panel__head"><h3>Demo accounts</h3><span className="label">Northwind Supply, synthetic data</span></div>
              <table className="table">
                <tbody>
                  {DEMO.map(([role, email, password]) => (
                    <tr key={email}>
                      <td>{role}</td>
                      <td className="measured">{email}</td>
                      <td className="text-right"><button type="button" className="btn btn--sm" onClick={() => setForm({ ...form, email, password })}>Fill in</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
