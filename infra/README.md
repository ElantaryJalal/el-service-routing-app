# Infra — EL Service Routing App

docker-compose stack for local development and deployment:

- **db** — PostgreSQL + PostGIS (primary database).
- **osrm** — OSRM routing engine, car profile, MLD pipeline.
- **vroom** — vroom-express optimisation server, routing via the osrm service.

## Usage

```bash
docker compose -f infra/docker-compose.yml up -d
```

Default published ports (override via env, keep backend URLs in sync):

| Service | Env var              | Default host port |
| ------- | -------------------- | ----------------- |
| db      | `POSTGRES_HOST_PORT` | 5432              |
| osrm    | `OSRM_HOST_PORT`     | 5000              |
| vroom   | `VROOM_HOST_PORT`    | 3000              |

> **OSRM will not start until its data is pre-processed** — do the one-time data
> prep below before `up`, or the osrm container will restart-loop.

---

## OSRM data prep (one-time)

Our stops span **Sachsen, Sachsen-Anhalt, and Thüringen**, so we build a single
OSRM dataset covering all three from Geofabrik extracts. All commands are run
from the **repo root**; data lives in `infra/osrm-data/`.

The OSRM dataset base name is `region` by default (override with the `OSRM_FILE`
env var). The steps below produce `infra/osrm-data/region.osrm*`.

### 1. Download the Geofabrik extracts

```bash
cd infra/osrm-data

curl -O https://download.geofabrik.de/europe/germany/sachsen-latest.osm.pbf
curl -O https://download.geofabrik.de/europe/germany/sachsen-anhalt-latest.osm.pbf
curl -O https://download.geofabrik.de/europe/germany/thueringen-latest.osm.pbf
```

### 2. Merge the extracts into one file

Because we use more than one extract, merge them with **osmium** into
`region.osm.pbf`:

```bash
# from infra/osrm-data
docker run --rm -v "$PWD:/data" stefda/osmium-tool \
  osmium merge /data/sachsen-latest.osm.pbf \
               /data/sachsen-anhalt-latest.osm.pbf \
               /data/thueringen-latest.osm.pbf \
  -o /data/region.osm.pbf --overwrite
```

> If you have `osmium` installed locally, you can run it directly instead of via
> Docker.

### 3. Run the OSRM MLD pipeline

Run from the **repo root**. The car profile ships in the image at `/opt/car.lua`.

```bash
docker run --rm -t -v "$PWD/infra/osrm-data:/data" osrm/osrm-backend \
  osrm-extract -p /opt/car.lua /data/region.osm.pbf

docker run --rm -t -v "$PWD/infra/osrm-data:/data" osrm/osrm-backend \
  osrm-partition /data/region.osrm

docker run --rm -t -v "$PWD/infra/osrm-data:/data" osrm/osrm-backend \
  osrm-customize /data/region.osrm
```

This leaves `region.osrm*` files in `infra/osrm-data/`. Now start the stack:

```bash
docker compose -f infra/docker-compose.yml up -d
```

### Alternative: whole of Germany

If the host has **≥ 16 GB RAM**, you can skip the merge and use the country
extract directly. Download `germany-latest.osm.pbf` into `infra/osrm-data/`,
name it `region.osm.pbf` (or set `OSRM_FILE`), and run only step 3:

```bash
cd infra/osrm-data
curl -O https://download.geofabrik.de/europe/germany-latest.osm.pbf
mv germany-latest.osm.pbf region.osm.pbf
# then run the three step-3 commands from the repo root
```

---

## Verifying

Once OSRM is up, the backend smoke test should pass:

```bash
cd backend && pytest tests/test_osrm_smoke.py
```

It requests a 3×3 duration matrix for three Leipzig points from OSRM `/table`.
