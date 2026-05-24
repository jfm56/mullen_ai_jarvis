# Frontend (placeholder)

Next.js (App Router) + Tailwind UI. Not yet scaffolded — bootstrap in Phase 2 alongside the Personal Assistant.

When ready:

```powershell
cd F:\Projects\mullen_ai_jarvis\frontend
npx create-next-app@latest . --typescript --tailwind --app --src-dir --import-alias "@/*"
```

Planned routes for v1 (Phase 2 scope):

- `/` — Today view: calendar + tasks + chat input
- `/inbox` — Email Assistant triage (Phase 4)
- `/projects` — Project Manager dashboard (Phase 5)
- `/marketing` — Content calendar + drafts (Phase 6)
- `/pipeline` — Lead Generation pipeline (Phase 6)
- `/approvals` — Pending agent actions awaiting your decision (Phase 1)
- `/memory` — View/edit/delete what Jarvis remembers (Phase 3)
- `/settings` — Permissions, integrations, voice config

Backend API lives at `http://127.0.0.1:8000` by default.
