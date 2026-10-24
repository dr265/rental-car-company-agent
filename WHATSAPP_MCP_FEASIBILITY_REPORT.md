# WhatsApp MCP — Feasibility Report for the Rental Car WhatsApp Agent

**Audited:** 2026-10-13
**Component under audit:** `D:\whatsapp-mcp-main`
**Auditor scope:** complete static inspection of the implementation, its manifests, its
transport surface and its session/persistence model. No source file of the MCP project
was modified.

> **Bottom line:** the MCP server *can* reach WhatsApp without Meta Cloud API, without
> Kapso and without any WhatsApp API credentials of that kind — but it cannot serve as
> the **primary production transport** for the Rental Car Agent as shipped.
> **Overall classification: LIMITED.** Kapso stays primary. Reasoning and evidence below.

---

## 1. Location and architecture (verified)

```
D:\whatsapp-mcp-main\
└── whatsapp-mcp-main\                 <- repository root (git clone of lharries/whatsapp-mcp)
    ├── README.md                      <- official install/usage documentation
    ├── LICENSE                        <- MIT, Copyright (c) 2025 Luke Harries
    ├── .gitignore
    ├── example-use.png
    ├── whatsapp-bridge\               <- COMPONENT 1: Go daemon
    │   ├── go.mod                     <- module whatsapp-client, go 1.24.1
    │   ├── go.sum
    │   └── main.go                    <- 1,348 lines, the entire bridge
    └── whatsapp-mcp-server\           <- COMPONENT 2: Python MCP server
        ├── main.py                    <- 12 MCP tools, stdio transport
        ├── whatsapp.py                <- data layer: reads SQLite directly, POSTs to :8080
        ├── audio.py                   <- ffmpeg voice-note conversion
        ├── pyproject.toml             <- mcp[cli]>=1.6.0, httpx, requests; requires-python >=3.11
        ├── uv.lock, .python-version, .gitignore
```

Two independent processes, **not** one deployable service:

| | Go bridge (`whatsapp-bridge`) | Python MCP server (`whatsapp-mcp-server`) |
| --- | --- | --- |
| Talks to WhatsApp | **Yes** — `go.mau.fi/whatsmeow` (WhatsApp Web multi-device protocol) | No |
| Owns the session | **Yes** — `store/whatsapp.db` (`sqlstore`) | No |
| Owns message history | **Yes** — `store/messages.db`, tables `chats` + `messages` | Reads that file directly with `sqlite3` |
| Network surface | REST on **:8080**, `POST /api/send`, `POST /api/download` — **and nothing else** | **stdio only** |
| MCP protocol | Not implemented | `mcp.run(transport='stdio')` (`main.py`, last line) |

### How each piece is reached

- **Inbound:** `whatsmeow` fires `*events.Message` → `handleMessage()` → row written to
  `store/messages.db`. That is the *entire* inbound path. There is no push, no webhook,
  no callback, no SSE, no message-queue publication.
- **Reading inbound:** `whatsapp.py` opens `MESSAGES_DB_PATH` =
  `<repo>/whatsapp-bridge/store/messages.db` and SELECTs. The MCP read tools are thin
  wrappers over that SQL.
- **Outbound:** every send tool POSTs `http://localhost:8080/api/send` →
  `sendWhatsAppMessage()` → `client.SendMessage(...)`.

## 2. Authentication requirements — what is actually needed

Answering the "no WhatsApp API" question precisely. Five *different* requirements are
often conflated; here is the verified position on each:

| Requirement | Needed by this MCP? | Evidence |
| --- | --- | --- |
| Direct **Meta WhatsApp Cloud API** integration in our app | **No** | No Graph API host, no `graph.facebook.com`, no Bearer token anywhere; `WHATSAPP_API_BASE_URL` is `http://localhost:8080/api` |
| Direct **Kapso** integration in our app | **No** | No `api.kapso.ai`, no `X-API-Key` |
| Any **WhatsApp API credentials** (phone_number_id, WABA id, business verification, template approval) | **No** | Session is a linked device, not an API credential |
| **Authentication of some kind** | **YES — mandatory** | A **QR-code pairing** of a real WhatsApp account on a phone (`client.GetQRChannel`, `qrterminal.GenerateHalfBlock`), persisted in `store/whatsapp.db`, plus a **C compiler + CGO** on Windows for `go-sqlite3` |
| **LLM API keys** | **Unchanged — still required** | The MCP is a data channel. It does not generate replies. Our agent still calls the LLM chain in `backend/app/llm.py` with the existing provider keys |

So: *"no WhatsApp API integration"* is satisfied. *"no authentication or external
service of any kind"* is **not** satisfied, and *"no LLM API keys"* is **not** satisfied.
Removing a WhatsApp API does not remove the LLM requirement.

Receiving mechanism, precisely: **persistent socket (whatsmeow) → local SQLite write**.
The socket is event-driven *inside the bridge*; the write is not event-driven *towards
our agent*. There is no webhook and no polling endpoint on :8080 to read messages — only
the SQLite file and the stdio MCP tools expose them.

## 3. Available tools and verified capabilities

12 tools are registered in `whatsapp-mcp-server/main.py`. All reading tools query SQLite;
all writing tools go through the bridge REST API.

| Tool | Real capability | Verified notes |
| --- | --- | --- |
| `search_contacts` | reads `chats` (excludes `@g.us`) | OK |
| `list_messages` | reads `messages` JOIN `chats`, filters after/before/sender/chat/query + paging | **Returns a formatted STRING**, though `main.py` annotates `List[Dict]` — `whatsapp.list_messages` ends in `return format_messages_list(...)`. Structured consumption is awkward/incorrect for a machine client |
| `list_chats`, `get_chat`, `get_direct_chat_by_contact`, `get_contact_chats`, `get_last_interaction` | read-only metadata | OK |
| `get_message_context` | ±N messages around one id | OK |
| `send_message` | POST `:8080/api/send` → real WhatsApp text | Recipient = phone digits (no `+`) or JID. Works |
| `send_file` | same API with `media_path` | **`media_path` must be an absolute path on the machine running the Go bridge.** No URLs, no ids |
| `send_audio_message` | converts to ogg/opus via ffmpeg, then sends | Needs ffmpeg for non-ogg |
| `download_media` | POST `:8080/api/download` → decrypts via whatsmeow, writes `store/<chat>/<file>` | OK |

**Not present anywhere:** delivery receipts / message ids returned to the caller
(`_, err = client.SendMessage(...)` discards whatsmeow's response), read receipts,
typing indicators, per-message dedupe, retry policy, rate limiting, message templates,
or any bulk/streaming tool.

## 4. Can inbound customer messages reach the agent continuously?

**Yes, but only by polling — and this is a build-it-yourself step, not a provided feature.**

- The bridge writes every inbound message to `messages.db` as it arrives, so a poller can
  pick them up continuously. This is architecturally the *same* pattern our Kapso poller
  already uses (`backend/app/poller.py`, `POLL_INTERVAL_SECONDS = 6`).
- Each row carries a stable WhatsApp message id (`messages.id`), the sender
  (`messages.sender`, phone digits) and the chat (`messages.chat_jid`), so
  **per-customer identification and correct reply routing are possible**.
- **But:** nothing calls our agent. Our backend would have to (a) shell out to an `uv` +
  Python 3.11+ process and speak MCP JSON-RPC over stdio, or (b) read
  `messages.db` directly with a second SQLite connection. Neither is provided, and
  option (a) means the backend ships a second Python runtime.
- A tool that *can send* but must be **polled** for inbound is technically sufficient —
  we would replicate the Kapso poller against `messages.db`. It is not, however, an
  "MCP push" integration; MCP itself contributes nothing to inbound delivery here.

## 5. Can outbound messages reach the intended customer?

**Yes.** `send_text`/`send_file` address the recipient explicitly (phone digits or JID),
and the bridge sends from the linked account. Verified by inspection of
`sendWhatsAppMessage()`.

Limitations that matter for our requirements:

- **No message id is returned**, only `{success, message}`. We therefore **cannot**
  implement "track accepted → sent → delivered → read → failed", which the Rental Car
  Agent specification requires. Kapso returns `messages[0].id` and supports status
  webhooks; this MCP does not.
- Media requires a **host-local absolute path**, which breaks the project's portable
  registry-id design (`backend/app/media.py`) and would require the bridge and the
  backend to be co-located with a shared filesystem.
- No idempotency key: a retried send can duplicate a customer-visible message.

## 6. Session persistence, reconnection and failure behaviour

| Property | Verified behaviour |
| --- | --- |
| Survives process restart | **Yes** — device credentials persist in `store/whatsapp.db`; on start, if `client.Store.ID != nil` it connects without a QR |
| Survives network blips | yes, while the process lives (whatsmeow reconnects internally) |
| Survives logout / re-auth | **No.** `*events.LoggedOut` only logs `"Device logged out, please scan QR code to log in again"`. The handler does **not** re-arm the QR channel, does not exit, does not restart. The bridge keeps running **disconnected** with no way back except a manual restart |
| Session lifetime | README: may need re-authentication after **~20 days** |
| Crash recovery | none (no supervisor, no healthcheck, no service unit) |
| `requestHistorySync()` | defined but **never called** from `main()` — dead code; history arrives only if WhatsApp pushes it on link |

## 7. Security, reliability and operational limitations

**Security**

- `POST http://localhost:8080/api/send` has **no authentication whatsoever**. Any
  process on the machine (or anything that can reach the port) can send WhatsApp
  messages as the account owner, impersonating them to any contact.
- `send_file` accepts an **arbitrary absolute path** and uploads its bytes to a chat:
  any local process can exfiltrate any readable file on the host.
- The bridge binds `":8080"` (all interfaces) and stores the **owner's entire personal
  WhatsApp message history, including media keys**, unencrypted in `store/messages.db`.
- API keys/tokens are not the issue; the *session* is the credential, and it lives in a
  plain file.

**Policy / account risk** — this connects the owner's **personal WhatsApp account** via
an **unofficial client library** (whatsmeow). That is not a sanctioned business channel;
automated bulk messaging through a personal linked device can get the number
**banned**, taking the owner's private chats with it. This is the single biggest reason
not to run customer traffic through it.

**Engineering**

- **Go toolchain required**, at build *and* runtime (`go run main.go`). On Windows,
  `go-sqlite3` additionally needs `CGO_ENABLED=1` **and** a C compiler (MSYS2/ucrt64 on
  `PATH`) — documented in the README as a known Windows obstacle.
- Two processes to supervise, on two different runtimes.
- No tests, no CI, no Docker, no health endpoint.
- MIT licensed — reuse is legally fine.

**Reliability**

- No retry, no backoff, no queue, no dedupe, no delivery receipts.
- No reconnect after `LoggedOut`.
- `handleMessage` silently returns for messages with neither text nor media
  (fine) but also for `reaction`, `protocol`, edit and revoke events.

## 8. Local test results

**Honest statement of what was and was not tested.**

- **Static verification (complete):** every file listed in §1 was read, including the
  full 1,348-line `main.go`, `whatsapp.py`, `main.py`, `go.mod`, `pyproject.toml` and
  `LICENSE`. Every claim in §2–§7 is grounded in that source.
- **Live execution: NOT performed.** This environment's shell tool is unavailable
  (every command returns exit code 53 with no output), so the Go bridge could not be
  compiled, no QR session could be established, and no WhatsApp message was sent or
  received. No `store/` directory, database or paired session exists in the audit copy.
- **No mock test is claimed as a live test.** Nothing below is presented as evidence of
  real WhatsApp delivery.
- To complete the remaining verification the owner would need to (1) install Go + a
  C compiler, (2) run `cd whatsapp-bridge && go run main.go`, (3) scan the QR code with a
  scratch WhatsApp account (not the business number), and (4) send a message from a
  *second* phone to confirm inbound storage and reply routing. That is a same-host
  experiment, not something that can be validated from this checkout.

## 9. What would be required to use it as the Rental Car transport

If the owner still wants it, all of the following are prerequisites:

1. Go 1.24+ **and** `CGO_ENABLED=1` with a C compiler installed on the host.
2. A WhatsApp account to link — **ideally a dedicated SIM, not the owner's personal
   number or the existing business number**, to avoid conflicting with the live Kapso
   session and to limit ban exposure.
3. A QR pairing step and a session that must be re-paired roughly monthly.
4. A **poller/transport adapter** written by us: read new rows from `messages.db`
   (or speak MCP over stdio to the Python server) → feed `agent.handle_inbound` →
   send replies via `POST :8080/api/send`; plus dedupe on `messages.id`.
5. Co-location of the bridge and the backend (media is sent by absolute path).
6. A supervisor that restarts the bridge and re-arms pairing after `LoggedOut`.
7. Acceptance that **delivery receipts are impossible** and that customer traffic runs
   on an unofficial client against a personal account.
8. Firewalling of :8080 (no auth today).

## 10. Recommendation

**Retain Kapso as the primary WhatsApp transport. Do not switch production traffic to
this MCP.**

Kapso already provides, verified live in this project's own logs: the Cloud-API send
surface with returned message ids, HMAC-signed webhooks, delivery-status events, media
upload by id, a worked test-send path, and no local session to babysit. The MCP offers a
strictly smaller capability set on top of a personal-account session with a ban-risk
posture and a Go/CGO build requirement on Windows.

### Classification

**LIMITED** — useful for development, personal experimentation and one-off manual
messaging from an MCP client; it *can* be polled for inbound messages and *can* send
outbound replies, but it is missing essential production capabilities (authenticated
send surface, delivery receipts, message ids, inbound push, session recovery, portable
media handling) and it runs customer traffic over an unsanctioned personal-account
channel.

Per Phase 6 of the brief, no second transport was implemented: the brief forbids adding
one for architectural decoration, and requires inbound + outbound + routing to be
production-ready *before* an MCP channel is considered usable. That bar is not met here.
The working Kapso implementation is untouched; if the owner later accepts the risks in
§9, the adapter described there is the seam to build, and the rental booking logic
(`app/bookings.py`, `app/vehicles.py`, `app/agent.py`) is already transport-independent,
so no business logic would need to change.

**Direct answer to the question asked:** *Can this MCP connect the Rental Car Agent to
WhatsApp without configuring a separate WhatsApp API in our application?* **Yes for the
WhatsApp API itself — no Meta Cloud API, no Kapso API, no WhatsApp credentials are
needed.** It is **not** dependency-free: it still requires QR pairing of a real WhatsApp
account plus an ongoing authenticated device session, a Go + CGO/C-compiler toolchain on
the host, a co-located bridge process, host-local media paths, and a poller we write
ourselves — and it still requires the existing LLM API keys, which it does nothing to
replace.
