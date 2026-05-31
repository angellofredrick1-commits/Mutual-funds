from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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
- Maximum 250 words total
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
# Takes raw admin-written text and returns a
# clean, WhatsApp-formatted market update
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
            model="claude-sonnet-4-20250514",
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
# Accepts either:
#   - A PDF file upload (multipart/form-data)
#   - Raw pasted text (from email or copied content)
# Returns a WhatsApp-ready market brief
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
        # ── PDF file uploaded ──────────────────────
        if file:
            if not file.filename.endswith(".pdf"):
                raise HTTPException(
                    status_code=400,
                    detail="Only PDF files are supported"
                )

            contents = await file.read()
            pdf_data = base64.standard_b64encode(contents).decode("utf-8")

            msg = client.messages.create(
                model="claude-sonnet-4-20250514",
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

        # ── Pasted text (email, copied content) ───
        else:
            msg = client.messages.create(
                model="claude-sonnet-4-20250514",
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
# Phase 1: logs the message to Railway console
# Phase 4: will call Meta Cloud API to broadcast
# ══════════════════════════════════════════════════
@app.post("/api/send")
async def send(
    message: str = Form(...),
    schedule_time: str = Form(None)
):
    """
    Phase 1: Logs the message — you copy-paste to WA manually.
    Phase 4: This route will call Meta Cloud API POST /messages.
    """
    if not message or not message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    timestamp = datetime.utcnow().isoformat()

    # Log to Railway console so you can see it
    print("=" * 50)
    print(f"[SOKOVIEW SEND] {timestamp}")
    if schedule_time:
        print(f"[SCHEDULED FOR] {schedule_time}")
    print(f"[MESSAGE]\n{message}")
    print("=" * 50)

    # Phase 4 — uncomment when Meta API is ready:
    # wa_response = send_to_whatsapp_channel(message)
    # return {"status": "sent", "wa_response": wa_response}

    return {
        "status": "queued",
        "timestamp": timestamp,
        "message_preview": message[:80] + "..." if len(message) > 80 else message,
        "note": "Phase 1 — copy this message and send to WA channel manually. Meta API broadcast coming in Phase 4."
    }


# ══════════════════════════════════════════════════
# ROUTE 5 — SAVE DRAFT  
# POST /api/draft
# Phase 1: returns confirmation
# Phase 2: will save to Supabase
# ══════════════════════════════════════════════════
@app.post("/api/draft")
async def save_draft(
    message: str = Form(...),
    message_type: str = Form("market_update")
):
    """
    Phase 1: Confirms draft saved (no DB yet).
    Phase 2: Will save to Supabase daily_briefs table.
    """
    if not message or not message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    timestamp = datetime.utcnow().isoformat()

    print(f"[DRAFT SAVED] {timestamp} | type: {message_type}")
    print(f"{message[:100]}...")

    # Phase 2 — uncomment when Supabase is ready:
    # save_to_supabase(message, message_type, timestamp)

    return {
        "status": "saved",
        "timestamp": timestamp,
        "message_type": message_type,
        "note": "Phase 2 — will persist to Supabase database"
    }
