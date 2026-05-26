"use client";

import { useRequireAuth } from "@/lib/auth";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export default function SettingsPage() {
  const user = useRequireAuth();
  if (!user) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <header>
        <h1 className="text-xl font-semibold text-brand-900">Settings</h1>
      </header>

      <div className="card space-y-2">
        <h2 className="text-sm font-semibold text-brand-900">Account</h2>
        <div className="text-sm text-brand-700">
          <div>username: <span className="font-mono">{user.username}</span></div>
          <div>display name: {user.display_name}</div>
          <div>role: {user.is_admin ? "admin" : "user"}</div>
          <div>id: <span className="font-mono text-xs">{user.id}</span></div>
        </div>
      </div>

      <div className="card space-y-2">
        <h2 className="text-sm font-semibold text-brand-900">Backend</h2>
        <div className="text-sm text-brand-700">
          API base: <span className="font-mono">{API_BASE}</span>
        </div>
        <p className="text-xs text-brand-500">
          Set <code>NEXT_PUBLIC_API_BASE</code> in <code>.env.local</code> to point
          this UI at a different backend (e.g. when running on a different host).
        </p>
      </div>

      <div className="card space-y-2">
        <h2 className="text-sm font-semibold text-brand-900">Not yet in the UI</h2>
        <p className="text-sm text-brand-700">
          The backend has 109 endpoints; this scaffold surfaces the highest-leverage
          ones (Today, Tasks, Approvals, Projects, Grants, generic Agent chat).
          Memory controls, opportunity pipeline, social drafts, lead pipeline,
          email triage, computer-control allow-list management, and backups all
          have REST APIs and land in the UI in later iterations.
        </p>
        <details className="text-xs text-brand-500">
          <summary className="cursor-pointer">Endpoints to exercise via curl/HTTP client</summary>
          <ul className="mt-2 list-inside list-disc space-y-1">
            <li><code>POST /memory</code>, <code>GET /memory?domain=…&amp;q=…</code></li>
            <li><code>GET /opportunities</code>, <code>POST /proposals/draft</code></li>
            <li><code>GET /emails</code>, <code>POST /emails/&#123;id&#125;/draft</code></li>
            <li><code>GET /leads</code>, <code>POST /leads/&#123;id&#125;/draft-outreach</code></li>
            <li><code>POST /social-posts/draft</code></li>
            <li><code>POST /computer/apps</code>, <code>POST /computer/run-script</code></li>
            <li><code>POST /grants/&#123;id&#125;/initialize</code>, <code>/screen-eligibility</code>, <code>/sections/&#123;sid&#125;/draft</code>, <code>/assemble</code>, <code>/finalize</code></li>
            <li><code>POST /backups</code> (admin only)</li>
          </ul>
        </details>
      </div>
    </div>
  );
}
