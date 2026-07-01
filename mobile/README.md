# Mobile — EL Service Routing App

Expo / React Native client (TypeScript, expo-router). M1 shipped the client
layer + navigable shell; **M2 adds the ingestion flow**: photograph a plan →
extract → confirm/edit stops → commit → Review (no maps yet).

## Setup

```bash
cd mobile
npm install
cp .env.example .env        # set EXPO_PUBLIC_API_BASE_URL (LAN IP for a phone)
npm run start               # then scan the QR code with Expo Go
```

On a physical phone, `localhost` points at the phone, not your machine — set
`EXPO_PUBLIC_API_BASE_URL` to your computer's LAN IP (e.g. `http://192.168.1.20:8000`).

## Structure

```
mobile/
├── app/                 # expo-router routes
│   ├── _layout.tsx      # Stack navigator
│   ├── index.tsx        # Capture — camera (expo-camera) / library (expo-image-picker) → extract
│   ├── confirm.tsx      # Confirm — edit draft stops, flag low-confidence, commit
│   ├── review.tsx       # Review (stub; optimise lands here next)
│   └── map.tsx          # Map (stub)
├── src/
│   ├── api/
│   │   ├── config.ts    # API base URL (expo-constants / EXPO_PUBLIC_API_BASE_URL)
│   │   ├── client.ts    # thin typed client wrapping every endpoint
│   │   └── types.ts     # GENERATED from the backend OpenAPI — do not edit
│   ├── components/
│   │   └── DraftStopCard.tsx  # one editable extracted stop
│   └── state/
│       └── draftStore.ts      # in-memory draft handed Capture → Confirm
└── app.config.ts        # Expo config; exposes extra.apiBaseUrl
```

## Ingestion flow (M2)

Capture takes/picks a photo and uploads it with `api.extractPlan()`, stashing the
returned draft in `src/state/draftStore.ts` and navigating to Confirm with the
tour id. Confirm renders each stop as an editable `DraftStopCard` (street,
postal_code, city, order_no, tasks, and a prominent `service_minutes` — the main
driver of the plan). Fields extracted with confidence `< 0.6` are flagged amber.
Edits persist per-field via `api.patchDraftStop()`; **Commit** calls
`api.commitTour()`, resolves any `duplicate_groups` via a merge/keep prompt, then
lands on Review.

> **Backend contract (provisional).** `POST /tours/extract`,
> `GET /tours/{id}/draft`, `PATCH /tours/{id}/draft/stops/{stop_id}`, and the
> `duplicate_groups` shape on commit are **not yet in the backend OpenAPI**. The
> client defines them as provisional types (see the `TODO(backend)` block in
> `src/api/client.ts`); regenerate `types.ts` and switch to generated types once
> the backend implements them.

## API types

`src/api/types.ts` is generated from the backend's `/openapi.json`; never edit it
by hand. Regenerate after backend contract changes (backend must be running):

```bash
EXPO_PUBLIC_API_BASE_URL=http://localhost:8000 npm run gen:api
```

The client (`src/api/client.ts`) wraps: `health` (temp), `extractPlan`,
`getDraft`, `patchDraftStop`, `patchStop`, `commitTour`, `optimiseTour`.
`extractPlan`, `getDraft`, `patchDraftStop`, and the `duplicate_groups` shape on
`commitTour` target endpoints not yet in the backend and use provisional types
until the backend adds them.

## Checks

```bash
npm run typecheck    # tsc --noEmit
npm run lint         # expo lint
```
