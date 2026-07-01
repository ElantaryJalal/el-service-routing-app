# Mobile — EL Service Routing App

Expo / React Native client (TypeScript, expo-router). This milestone (M1) is the
**client layer + navigable shell** only — no feature screens yet.

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
│   ├── index.tsx        # Capture (+ temporary "Test connection" button)
│   ├── confirm.tsx      # Confirm (stub)
│   ├── review.tsx       # Review (stub)
│   └── map.tsx          # Map (stub)
├── src/api/
│   ├── config.ts        # API base URL (expo-constants / EXPO_PUBLIC_API_BASE_URL)
│   ├── client.ts        # thin typed client wrapping every endpoint
│   └── types.ts         # GENERATED from the backend OpenAPI — do not edit
└── app.config.ts        # Expo config; exposes extra.apiBaseUrl
```

## API types

`src/api/types.ts` is generated from the backend's `/openapi.json`; never edit it
by hand. Regenerate after backend contract changes (backend must be running):

```bash
EXPO_PUBLIC_API_BASE_URL=http://localhost:8000 npm run gen:api
```

The client (`src/api/client.ts`) wraps: `health` (temp), `extractPlan`,
`getDraft`, `patchStop`, `commitTour`, `optimiseTour`. `extractPlan` and
`getDraft` target endpoints not yet in the backend and use small provisional
types until the backend adds them.

## Checks

```bash
npm run typecheck    # tsc --noEmit
npm run lint         # expo lint
```
