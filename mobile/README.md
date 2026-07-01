# Mobile — EL Service Routing App

Expo / React Native client (TypeScript, expo-router).

- **M1** — client layer + navigable shell.
- **M2** — ingestion flow: photograph a plan → extract → confirm/edit → commit.
- **M3** — optimisation + map: review/override closing times → optimise → a
  day-filtered map with ETAs, stop details, navigate, and offline caching.

## Setup

```bash
cd mobile
npm install
cp .env.example .env        # set EXPO_PUBLIC_API_BASE_URL (LAN IP for a phone)
```

On a physical device, `localhost` points at the phone, not your machine — set
`EXPO_PUBLIC_API_BASE_URL` to your computer's LAN IP (e.g. `http://192.168.1.20:8000`).

## Running: dev build required from M3 on

M3 added **`react-native-maps`**, a native module that is **not** in the Expo Go
sandbox. From here you run a **custom dev build**, not Expo Go. Capture/Confirm/
Review still work in Expo Go, but the Map screen needs the dev build.

### 1. Google Maps key (Android only)

Android maps need a Google Maps key; iOS uses Apple Maps and needs none. Enable
**"Maps SDK for Android"** in Google Cloud, then put the key in `.env`:

```bash
GOOGLE_MAPS_ANDROID_API_KEY=AIza...
```

`app.config.ts` passes it to the `react-native-maps` config plugin, which writes
it into the native `AndroidManifest.xml`. It's consumed at **build time**, so it
must be set before prebuild / EAS build (it is not a runtime `EXPO_PUBLIC_` var).

### 2a. Local prebuild (device/emulator on this machine)

```bash
npx expo prebuild                 # generates ./android and ./ios (git-ignored)
npx expo run:android              # or: npx expo run:ios
```

### 2b. EAS dev build (recommended; no local native toolchain)

```bash
npm i -g eas-cli && eas login
eas build --profile development --platform android   # or ios
# install the resulting build, then:
npx expo start --dev-client
```

`android/` and `ios/` are git-ignored (continuous native generation) — never
commit them; re-run `expo prebuild` after changing native config/plugins.

## Structure

```
mobile/
├── app/                 # expo-router routes
│   ├── _layout.tsx      # Stack navigator
│   ├── index.tsx        # Capture — camera (expo-camera) / library (expo-image-picker) → extract
│   ├── confirm.tsx      # Confirm — edit draft stops, flag low-confidence, commit
│   ├── review.tsx       # Review — override closing/service times → optimise
│   └── map.tsx          # Map — day-filtered optimised route, details, navigate
├── src/
│   ├── api/
│   │   ├── config.ts    # API base URL (expo-constants / EXPO_PUBLIC_API_BASE_URL)
│   │   ├── client.ts    # thin typed client wrapping every endpoint
│   │   └── types.ts     # GENERATED from the backend OpenAPI — do not edit
│   ├── components/
│   │   ├── DraftStopCard.tsx   # one editable extracted stop (Confirm)
│   │   └── ReviewStopCard.tsx  # closing/service-time editor (Review)
│   ├── domain/
│   │   └── optimisedTour.ts    # compose OptimiseResult + stop detail; day colours
│   └── state/
│       ├── draftStore.ts       # in-memory draft handed Capture → Confirm
│       └── tourCache.ts        # AsyncStorage cache of the optimised tour (offline)
└── app.config.ts        # Expo config; API base URL + native map key plugin
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

## Optimisation + map (M3)

After commit, **Review** loads the geocoded stops (`api.getStops()`) and lets you
override each market's `closing_time` (prefilled from OSM and badged "from map
data (check me)" vs "set by you") and `service_minutes` — a wrong closing time can
make a whole day infeasible. Edits persist via `api.patchStop()`. **Optimise**
calls `api.optimiseTour()`, joins the result with stop detail into an
`OptimisedTour` (`src/domain/optimisedTour.ts`), caches it (see Offline), and
opens **Map**.

**Map** (`react-native-maps`) shows every assigned stop as a marker coloured by
day. A day filter (All / one chip per day) narrows the view; picking a single day
draws its stops in sequence as a polyline. Tapping a marker opens a detail card
(customer, address, task chips, day, sequence, ETA, service minutes, closing
time) — highlighted red when the ETA is within ~30 min of closing — with a
**Navigate** button that deep-links to Apple/Google Maps. Overflow stops from
optimise appear in an **"N markets don't fit this week"** banner with reasons.

**Offline.** The composed tour is cached in AsyncStorage (`src/state/tourCache.ts`)
whenever optimise runs, so Map loads cache-first and the map, day filter, and
detail cards keep working with no signal.

> **Backend contract (provisional).** The polyline is straight-line in v1 —
> `TODO(backend)`: expose per-day OSRM geometry. `GET /tours/{id}/stops` and the
> coordinate/address/task fields on `StopDetail` are **not yet in the backend
> OpenAPI**; the client defines them provisionally (see `TODO(backend)` in
> `src/api/client.ts`).

## API types

`src/api/types.ts` is generated from the backend's `/openapi.json`; never edit it
by hand. Regenerate after backend contract changes (backend must be running):

```bash
EXPO_PUBLIC_API_BASE_URL=http://localhost:8000 npm run gen:api
```

The client (`src/api/client.ts`) wraps: `health` (temp), `extractPlan`,
`getDraft`, `patchDraftStop`, `patchStop`, `commitTour`, `getStops`,
`optimiseTour`. `extractPlan`, `getDraft`, `patchDraftStop`, `getStops`, and the
`duplicate_groups` shape on `commitTour` target endpoints not yet in the backend
and use provisional types until the backend adds them.

## Checks

```bash
npm run typecheck    # tsc --noEmit
npm run lint         # expo lint
```
