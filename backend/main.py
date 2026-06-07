from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic
from supabase import create_client, Client
import os, base64, json, httpx
from datetime import datetime

# ── APP SETUP ─────────────────────────────────────
app = FastAPI(
    title="Sokoview Backend",
    description="Claude-powered DSE market intelligence API",
    version="1.0.0"
)

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ── SUPABASE SETUP ────────────────────────────────
supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_SECRET")
)

# ── WHATSAPP CONFIG ───────────────────────────────
WA_TOKEN = os.environ.get("WA_TOKEN")
WA_PHONE_ID = os.environ.get("WA_PHONE_ID")
WA_WEBHOOK_SECRET = os.environ.get("WA_WEBHOOK_SECRET", "sokoview_verify_token")

# ── CORS ──────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://trysokoview.today",
        "https://www.trysokoview.today",
        "https://*.netlify.app",
        "http://localhost:3000",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── CLAUDE SYSTEM PROMPT ──────────────────────────
SYSTEM_PROMPT = """
You are a DSE market analyst writing for Sokoview — a Tanzanian
retail investor platform. Your audience is everyday investors
who follow the Dar es Salaam Stock Exchange.

STRICT FORMATTING RULES for WhatsApp:
- Use *asterisks* for bold — e.g. *CRDB up 2.3% today*
- Use • for bullet points — one space after the bullet
- Maximum 150 words total
- No markdown headers (no #, ##, ###)
- No hashtags
- No emojis unless specifically asked
- End every message with a divider line —— followed by
  a 2-3 line Swahili summary of the key point
- Last line always: *Fuatilia portfolio yako: sokoview.co.tz*

CONTENT PRIORITY (in order):
1. Single most important story as the opening line
2. Top movers — price, change, volume if available
3. Dividend or AGM events this week
4. One clear takeaway or investor action point
5. Swahili summary

TONE:
- Clear and direct — not formal or academic
- Friendly but credible
- Write as if texting a smart friend who follows the DSE
"""


# ══════════════════════════════════════════════════
# HELPER — SEND WHATSAPP MESSAGE
# ══════════════════════════════════════════════════
async def send_whatsapp_message(to: str, message: str):
    """Send a plain text WhatsApp message via Meta Cloud API."""
    url = f"https://graph.facebook.com/v25.0/{WA_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WA_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    async with httpx.AsyncClient() as http:
        response = await http.post(url, headers=headers, json=payload)
        print(f"[WA SEND] {response.status_code} → {response.text}")
        return response


# ══════════════════════════════════════════════════
# HELPER — SAVE SUBSCRIBER TO SUPABASE
# ══════════════════════════════════════════════════
async def save_subscriber(phone: str, name: str = None):
    """
    Upsert a subscriber into the subscribers table.
    Uses phone as unique key — won't duplicate.
    """
    try:
        result = supabase.table("subscribers").upsert(
            {"phone": phone, "name": name, "is_active": True},
            on_conflict="phone"
        ).execute()
        print(f"[SUBSCRIBER SAVED] {phone}")
        return result
    except Exception as e:
        print(f"[SUBSCRIBER ERROR] {e}")
        return None


# ══════════════════════════════════════════════════
# ROUTE 1 — HEALTH CHECK
# ══════════════════════════════════════════════════
@app.get("/")
async def health():
    return {
        "status": "live",
        "service": "Sokoview Backend",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


# ══════════════════════════════════════════════════
# ROUTE 2 — POLISH TEXT
# POST /api/polish
# ══════════════════════════════════════════════════
@app.post("/api/polish")
async def polish(text: str = Form(...)):
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"""Polish this market update into a clean 
WhatsApp message following all the formatting rules.

Keep all the facts exactly as written — only improve 
the clarity, structure, and WhatsApp formatting:

---
{text}
---"""
                }
            ]
        )
        return {
            "status": "success",
            "result": msg.content[0].text,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════
# ROUTE 3 — PROCESS PDF OR EMAIL TEXT
# POST /api/process-pdf
# ══════════════════════════════════════════════════
@app.post("/api/process-pdf")
async def process_pdf(
    file: UploadFile = File(None),
    text: str = Form(None)
):
    if not file and not text:
        raise HTTPException(
            status_code=400,
            detail="Provide either a PDF file or pasted text"
        )

    try:
        if file:
            if not file.filename.endswith(".pdf"):
                raise HTTPException(
                    status_code=400,
                    detail="Only PDF files are supported"
                )

            contents = await file.read()
            pdf_data = base64.standard_b64encode(contents).decode("utf-8")

            msg = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_data,
                                }
                            },
                            {
                                "type": "text",
                                "text": """Read this DSE document carefully.
Extract all key market information — stock prices, 
percentage changes, dividends, AGMs, corporate actions, 
top movers, analyst notes.

Then write a WhatsApp-ready market brief following 
all the formatting rules. Prioritise the most 
impactful information for a retail DSE investor."""
                            }
                        ]
                    }
                ]
            )

        else:
            msg = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"""Convert this DSE market content into 
a WhatsApp-ready brief. Extract the most important 
information and rewrite it following all the 
formatting rules.

---
{text}
---"""
                    }
                ]
            )

        return {
            "status": "success",
            "result": msg.content[0].text,
            "source": "pdf" if file else "text",
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════
# ROUTE 4 — SEND MESSAGE
# POST /api/send
# ══════════════════════════════════════════════════
@app.post("/api/send")
async def send(
    message: str = Form(...),
    schedule_time: str = Form(None)
):
    if not message or not message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    timestamp = datetime.utcnow().isoformat()

    print("=" * 50)
    print(f"[SOKOVIEW SEND] {timestamp}")
    if schedule_time:
        print(f"[SCHEDULED FOR] {schedule_time}")
    print(f"[MESSAGE]\n{message}")
    print("=" * 50)

    return {
        "status": "queued",
        "timestamp": timestamp,
        "message_preview": message[:80] + "..." if len(message) > 80 else message,
        "note": "Phase 1 — copy this message and send to WA channel manually. Meta API broadcast coming in Phase 4."
    }


# ══════════════════════════════════════════════════
# ROUTE 5 — SAVE DRAFT
# POST /api/draft
# ══════════════════════════════════════════════════
@app.post("/api/draft")
async def save_draft(
    message: str = Form(...),
    message_type: str = Form("market_update")
):
    if not message or not message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    timestamp = datetime.utcnow().isoformat()

    print(f"[DRAFT SAVED] {timestamp} | type: {message_type}")
    print(f"{message[:100]}...")

    return {
        "status": "saved",
        "timestamp": timestamp,
        "message_type": message_type,
        "note": "Phase 2 — will persist to Supabase database"
    }


# ══════════════════════════════════════════════════
# ROUTE 6 — WHATSAPP WEBHOOK
# GET  /webhook — Meta verification
# POST /webhook — incoming messages
# ══════════════════════════════════════════════════
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == WA_WEBHOOK_SECRET:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()
    print(f"[WEBHOOK RECEIVED] {json.dumps(data)}")

    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "ok"}

        msg = messages[0]
        from_number = msg.get("from")
        msg_type = msg.get("type")
        msg_text = ""

        if msg_type == "text":
            msg_text = msg.get("text", {}).get("body", "").strip().upper()

        print(f"[MESSAGE FROM] {from_number}: {msg_text}")

        # ── SUBSCRIBE command ──────────────────────
        if msg_text == "SUBSCRIBE":
            await save_subscriber(phone=from_number)
            await send_whatsapp_message(
                to=from_number,
                message=(
                    "✅ *Umejisajili kikamilifu!*\n\n"
                    "Utapokea masasisho ya soko la DSE kila siku.\n\n"
                    "Welcome to Sokoview Analytics — you'll receive daily "
                    "DSE market briefs from us.\n\n"
                    "——\n"
                    "Send *STOP* at any time to unsubscribe.\n"
                    "*sokoview.co.tz*"
                )
            )

        # ── STOP / UNSUBSCRIBE command ─────────────
        elif msg_text in ["STOP", "UNSUBSCRIBE"]:
            try:
                supabase.table("subscribers").update(
                    {"is_active": False}
                ).eq("phone", from_number).execute()
            except Exception as e:
                print(f"[UNSUBSCRIBE ERROR] {e}")

            await send_whatsapp_message(
                to=from_number,
                message=(
                    "Umefuta usajili wako. Hutapokea masasisho zaidi.\n\n"
                    "You have been unsubscribed from Sokoview Analytics.\n"
                    "Send *SUBSCRIBE* anytime to rejoin."
                )
            )

        # ── Unknown message ────────────────────────
        else:
            await send_whatsapp_message(
                to=from_number,
                message=(
                    "Habari! 👋 Welcome to *Sokoview Analytics*.\n\n"
                    "Send *SUBSCRIBE* to receive daily DSE market briefs.\n"
                    "Send *STOP* to unsubscribe.\n\n"
                    "*sokoview.co.tz*"
                )
            )

    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")

    return {"status": "ok"}


# ══════════════════════════════════════════════════
# ROUTE 7 — LIST SUBSCRIBERS
# GET /api/subscribers
# ══════════════════════════════════════════════════
@app.get("/api/subscribers")
async def list_subscribers():
    try:
        result = supabase.table("subscribers").select("*").eq(
            "is_active", True
        ).execute()
        return {
            "status": "success",
            "count": len(result.data),
            "subscribers": result.data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
