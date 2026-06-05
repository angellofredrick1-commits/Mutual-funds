from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic
import os, base64, json
from datetime import datetime

# ── APP SETUP ─────────────────────────────────────
app = FastAPI(
    title="Sokoview Backend",
    description="Claude-powered DSE market intelligence API",
    version="1.0.0"
)

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ── CORS — allow your Netlify domain ──────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://trysokoview.today",
        "https://www.trysokoview.today",
        "https://*.netlify.app",   # covers Netlify preview URLs
        "http://localhost:3000",   # local testing
        "http://localhost:5500",   # VS Code live server
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
# ROUTE 1 — HEALTH CHECK
# GET /
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
    """
    Takes rough text written by admin,
    polishes it into a WhatsApp-ready brief.
    """
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
    """
    Converts a DSE PDF report or pasted email content
    into a WhatsApp-ready market brief using Claude.
    """
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
# GET  /webhook  — Meta verification
# POST /webhook  — incoming messages
# ══════════════════════════════════════════════════
WA_WEBHOOK_SECRET = os.environ.get("WA_WEBHOOK_SECRET", "sokoview_verify_token")

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    """
    Meta calls this endpoint to verify your webhook.
    It sends hub.mode, hub.challenge, and hub.verify_token.
    We check the token matches and return the challenge.
    """
    if hub_mode == "subscribe" and hub_verify_token == WA_WEBHOOK_SECRET:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Meta sends incoming messages and status updates here.
    Phase 1: just logs them.
    Phase 4: will process and trigger responses.
    """
    data = await request.json()
    print(f"[WEBHOOK RECEIVED] {json.dumps(data)}")
    return {"status": "ok"}
