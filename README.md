# ZoomRideXX Car Rentals — Website + WhatsApp AI Agent

The **customer website** (React + TypeScript), the **WhatsApp booking agent** and
the **owner console** — one project, one backend, one database.

Customers can book on the website (real availability, live prices, instant
RC-XXXXXX confirmation) or on WhatsApp through the same AI agent. The owner
gets an instant WhatsApp alert for every booking, whichever channel it came
from.

> _Driven by comfort, Trusted for cleanliness._

---

## The website (customer-facing, `/`)

Rebuilt from the original `index.html` design in React + TypeScript at the
root route:

| Section | What it does |
| --- | --- |
| Hero | Quick search (duration + vehicle type), interactive spotlight card |
| Fleet & rates | Live search, 6h/12h/24h toggle, category filters — every card reads the real fleet table |
| Vehicle details | Specs, full rate card, deposit, server-verified availability check |
| Booking form | Pickup/return scheduling, self-drive or chauffeur, hub or doorstep, **live server-side quote**, real confirmation with an `RC-` reference |
| Book on WhatsApp | Every booking CTA also opens the business WhatsApp chat prefilled with the car, dates and mode |
| AI Concierge | A real chat with the SAME agent brain that answers WhatsApp — grounded in the live fleet, hands off to the booking form when you confirm |
| Owner console | `/console` — dashboard, fleet CRUD, bookings, owner chat, knowledge, persona, media, connection |

Booking data flows both ways: a website booking is visible to the agent (so a
customer who asks on WhatsApp gets grounded answers about their reservation),
and WhatsApp bookings appear in the owner console and website status lookup.

## The WhatsApp customer flow

| Step | What the customer sees |
| --- | --- |
| 1 | First message → **English** / **हिंदी** buttons |
| 2 | Main menu → **Book a Car** · **Deposit & KYC Rules** · **Call Fleet Desk** |
| 3 | Browse → **By Category** · **By Duration (6h / 12h / 24h)** · **Type Car Name** |
| 4 | Interactive list of the fleet, grouped by category |
| 5 | Car card with 6h / 12h / 24h rates and refundable deposit |
| 6 | **Self-Drive** / **With Chauffeur** |
| 7 | Pickup date → time → **Hub Self-Pickup** / **Doorstep Delivery** |
| 8 | KYC — send licence + ID photos on WhatsApp, or show originals at handover |
| 9 | Summary (car, duration, mode, delivery, schedule, rent, deposit, cleanliness guarantee) → **Confirm Booking** |
| 10 | Confirmed reference, handover message, instant owner alert |

Everything is deterministic: buttons and list rows carry stable ids, the flow
state is persisted per conversation, and prices are read from the database —
never invented by the model. The LLM is only used for genuine free-form
questions (and is grounded in the live fleet).

## Fleet and rates

17 cars, seeded in `backend/app/seed.py`:

| Car | 6h | 12h | 24h |
| --- | --- | --- | --- |
| Mahindra Thar Roxx | — | ₹3,500 | ₹5,000 |
| Mahindra Thar 4x4 | — | ₹2,800 | ₹4,000 |
| Mahindra Scorpio N | — | ₹2,800 | ₹4,000 |
| Mahindra Scorpio S11 | — | ₹2,800 | ₹4,000 |
| Mahindra XUV 700 | — | ₹3,500 | ₹5,000 |
| Ford Endeavour | — | ₹6,000 | ₹10,000 |
| Toyota Fortuner | — | ₹10,000 | ₹14,000 |
| Maruti Ertiga | ₹1,000 | ₹2,200 | ₹3,000 |
| Maruti Fronx | ₹1,000 | ₹1,200 | ₹2,100 |
| Maruti Dzire | ₹1,000 | ₹1,200 | ₹2,100 |
| Maruti Baleno | ₹1,000 | ₹1,500 | ₹2,400 |
| Maruti Swift | ₹1,000 | ₹1,500 | ₹2,400 |
| Hyundai Aura | ₹1,000 | ₹1,500 | ₹2,400 |
| Maruti Brezza | ₹1,200 | ₹1,800 | ₹2,700 |
| Hyundai Creta | ₹1,200 | ₹1,800 | ₹2,700 |
| Hyundai Verna | ₹1,500 | ₹2,200 | ₹3,000 |
| Hyundai Venue | ₹1,500 | ₹2,200 | ₹3,000 |

Deposits: hatchback/sedan ₹3,000, compact SUV/SUV ₹5,000,
Fortuner/Endeavour ₹10,000. The deposit is refundable after check-in.

Each car has a photo under `backend/assets/images/` and an entry in
`backend/app/media.py`, so "send me the Thar photo" returns the labelled image.
"Show all photos" sends the full gallery and the console shows it as one
swipeable album.

## Running locally

Requirements: Python 3.11+ and — only for rebuilding the UI — Node.js 18+ / npm.

```bat
cd /d "C:\rental_car_company agent"
start.bat
```

`start.bat`:

1. checks `backend\.env`,
2. creates `backend\.venv` if missing and installs `backend\requirements.txt`,
3. builds the Next.js frontend (website + console) into `frontend\out` if it
   is missing (`start.bat rebuild` forces a fresh build),
4. frees port 8022,
5. starts the backend and opens `http://localhost:8022/` (the website) once
   `/api/health` responds.

The backend serves the exported frontend itself, so no separate Node server is
needed at runtime.

| URL | Purpose |
| --- | --- |
| `http://localhost:8022/` | Customer website (fleet, booking, concierge) |
| `http://localhost:8022/console` | Owner console + WhatsApp simulator |
| `http://localhost:8022/docs` | API documentation |
| `http://localhost:8022/api/health` | Health check |

Manual start:

```bat
cd backend
.venv\Scripts\activate
python main.py
```

Manual console build (only when changing the UI):

```bat
cd frontend
npm install
npm run build
```

## Deploying (Vercel + a real backend host)

The project has **two halves** and both must be deployed:

| Piece | What it is | Where it can run |
| --- | --- | --- |
| Frontend (`frontend/out`) | Static export of the website + console | Vercel / Netlify / any static host ✅ |
| Backend (`backend/`) | FastAPI + SQLite + WhatsApp poller + LLM chain | **A Python host with a persistent process** — Render.com, Railway, Fly.io, a VPS — or your own PC behind a tunnel. ❌ **NOT Vercel static hosting.** |

> Uploading the project ROOT folder to Vercel serves the old
> `original-design-reference.html` (the pre-React design file, renamed so this
> mistake fails loudly) with its old hardcoded WhatsApp number — and no API at
> all. Deploy the `frontend` folder, never the project root.

### 1. Backend

1. Push the repo to GitHub, create a **Render.com Web Service** (or Railway)
   from `backend/`: build `pip install -r requirements.txt`, start
   `uvicorn main:app --host 0.0.0.0 --port $PORT`.
2. Set the env vars (copy of `backend/.env`): `KAPSO_*`, the LLM keys,
   `OWNER_WHATSAPP_NUMBERS`, `WA_BUSINESS_NUMBER=12082475436`,
   `DATABASE_URL=sqlite:///data/rental_agent.db` (attach a persistent disk, or
   bookings reset on redeploy), `PUBLIC_BASE_URL=https://<backend-url>` and
   `FRONTEND_ORIGIN=https://<your-vercel-app>.vercel.app` (CORS).
3. WhatsApp delivery: register `https://<backend-url>/api/whatsapp/webhook`
   (event `whatsapp.message.received`, secret = `KAPSO_WEBHOOK_SECRET`) in
   Kapso — **or** let the built-in poller run on the hosted backend. Only ONE
   instance may poll the same number (`SHARED_NUMBER_LOCK=1`); stop your local
   instance when the hosted one takes over.
4. Quick alternative with zero new accounts: run `start.bat` locally and
   expose it with a tunnel (`cloudflared tunnel --url http://localhost:8022`),
   then use the tunnel URL as `<backend-url>`.

### 2. Frontend on Vercel

1. In Vercel, deploy the **`frontend` folder** (Git: set the project's *Root
   Directory* to `frontend`; folder upload: upload the **contents of
   `frontend\out`** after building — never the project root).
2. Environment variables (Project Settings → Environment Variables, then
   redeploy):
   - `NEXT_PUBLIC_API_URL=https://<backend-url>` — every API call goes there
   - `NEXT_PUBLIC_WA_NUMBER=12082475436` — fallback baked into the static
     build so "Book on WhatsApp" links stay correct even if the API blips
3. `frontend/public/vercel.json` (copied into `out/`) sets
   `trailingSlash: true` so `/console` resolves to the exported console.
4. Verify: open the site, the fleet loads with photos, and the WhatsApp
   buttons open the **+1 208-247-5436** chat.

## WhatsApp connection

Two inbound paths are supported:

1. **Poller** — works locally without a public URL; it reads new messages from
   Kapso and runs them through the same pipeline.
2. **Signed webhook** — register
   `https://<public-host>/api/whatsapp/webhook` in Kapso for the
   `whatsapp.message.received` event with the same secret as
   `KAPSO_WEBHOOK_SECRET`. `PUBLIC_BASE_URL` must be a public HTTPS address.

Webhooks are HMAC-verified, replayed message ids are deduplicated, and delivery
callbacks update outbound message rows. A successful API call is never reported
as "delivered".

**One number, one replying agent.** `SHARED_NUMBER_LOCK=1` keeps this agent from
double-replying when another process still uses the same WhatsApp number. The
console and API keep working; polling/replies resume when the other process is
stopped.

## Owner console

Open `http://localhost:8022/console` and sign in with the owner credentials from
`backend/.env` (`ADMIN_EMAIL` / `ADMIN_PASSWORD` — see `.env.example`). A
successful login issues the admin API token; when `ADMIN_AUTH_REQUIRED=1` the
backend enforces it on every mutating call as well.

| Panel | What it does |
| --- | --- |
| Dashboard | Live counts, booking value, intent mix and recent activity |
| Owner chat | Read customer threads, group photo albums, take over, reply as staff, resume the AI |
| Bookings | Real bookings with status transitions and staff-side cancellation |
| Fleet | Create/edit cars, 6h/12h/24h rates, deposit, photo; CSV/XLSX import |
| Owner assistant | Read-only summaries grounded in the live fleet/bookings snapshot |
| Knowledge | Upload and search PDF/DOCX/XLSX/CSV/TXT/JSON/Markdown documents |
| Persona | Business name, assistant tone, hours and policies; the rental core role is locked |
| Images | Browse the media registry, upload/delete, copy delivery URLs |
| Connection | Kapso credential check, webhook URL, run/pause |

## Booking mechanics

- A booking draft is created server-side; totals, deposit and chauffeur/delivery
  fees are computed from the fleet row, not from model text.
- Confirmation is idempotent (`source_message_id`) and assigns an `RC-XXXXXX`
  reference.
- Confirmed bookings trigger an owner alert to `OWNER_WHATSAPP_NUMBERS`
  (default `9179642928,9516108857`).
- Staff can cancel from the console even after the rental has started.

## Languages

- English
- Hindi / Hinglish (Devanagari and Latin script)

The language list lives in `backend/app/languages.py` only. An explicit
selection is sticky; a later message in another language does not override it.
Detection is deterministic (script ranges + Hinglish markers), so the first
reply is already in the right language without an LLM call.

## Configuration

See `backend/.env.example`.

- `KAPSO_API_KEY`, `KAPSO_PHONE_NUMBER_ID`, `KAPSO_WEBHOOK_SECRET` — WhatsApp.
- `PUBLIC_BASE_URL` — public HTTPS origin for the webhook.
- `OWNER_WHATSAPP_NUMBERS` — comma-separated numbers for booking alerts.
- `WA_BUSINESS_NUMBER` — WhatsApp number used by the website's "Book on
  WhatsApp" links (defaults to `91` + the first fleet-desk number).
- `DATABASE_URL` — SQLite path (`backend/data/rental_agent.db`).
- LLM keys/base URLs — failover chain for free-form answers (shared by the
  WhatsApp agent AND the website concierge).
- `SHARED_NUMBER_LOCK` — prevents a second agent on the same number.
- `MEDIA_PUBLIC_BASE_URL` — optional public image host; blank means direct upload.
- `ADMIN_API_TOKEN` / `ADMIN_AUTH_REQUIRED` — admin guard for mutating APIs
  (the console has an admin-token padlock in its header for when it's on).

Secrets stay server-side; the browser only calls `/api/...`.

## Project layout

```
backend/            FastAPI app, deterministic flow, database, seed, images
  app/rental_flow.py   the 10-step WhatsApp booking flow
  app/routers/website.py  the customer-website API (fleet, quotes, bookings, concierge)
  app/agent.py         the shared agent brain (WhatsApp + website concierge)
  app/menu.py          all WhatsApp copy, ids and formatting
  app/media.py         image registry and resolution
  app/seed.py          17-car fleet, FAQs, settings
frontend/           Next.js static export
  src/app/page.tsx        customer website (root route)
  src/app/console/        owner console (/console)
  src/components/site/    website components (hero, fleet, booking, concierge…)
tests/              pytest suite (incl. test_website_api.py for the site APIs)
start.bat           one-click local launcher
```

## Website booking mechanics (Option B)

- `POST /api/site/quote` returns a deterministic breakdown — package price for
  exact 6/12/24-hour windows, whole days × published full-day rate otherwise;
  chauffeur and delivery fees included; deposit always listed separately.
- `POST /api/site/bookings` validates the window server-side (lead time, max
  duration, past dates), re-checks overlap against CONFIRMED bookings, recomput
  the money from the fleet row, and only then persists a confirmed booking
  with a unique `RC-XXXXXX` reference and an idempotency key (a retried submit
  can never double-book). The fleet desk gets the same WhatsApp alert as for
  WhatsApp bookings.
- `GET /api/site/bookings/{reference}?phone=` is scoped to the customer's
  number — a wrong number is a plain 404, so references never leak bookings.
