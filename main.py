import os
from datetime import datetime
from typing import List, Optional, Literal, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import create_document, get_documents, db

app = FastAPI(title="AI Business Consultant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Utility: BSON/Datetime serialization
# -----------------------------

def serialize_doc(doc: dict) -> dict:
    def _convert(value: Any):
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, list):
            return [_convert(v) for v in value]
        if isinstance(value, dict):
            return {k: _convert(v) for k, v in value.items()}
        return value

    return _convert(doc)


# -----------------------------
# Schemas
# -----------------------------

class ConsultationCreate(BaseModel):
    business_name: str = Field(..., description="Your company or idea name")
    industry: str = Field(..., description="Industry or niche")
    stage: str = Field("idea", description="Stage: idea, mvp, growth, scale")
    goal: str = Field(..., description="Primary goal for this session")
    notes: Optional[str] = Field(None, description="Optional context")


class Consultation(BaseModel):
    id: str
    business_name: str
    industry: str
    stage: str
    goal: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class Message(BaseModel):
    id: str
    consultation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# -----------------------------
# Simple Advisor Logic (no external APIs)
# -----------------------------

def generate_advice(user_text: str, meta: ConsultationCreate) -> str:
    """Heuristic advisor response.
    Produces structured, actionable guidance based on the prompt and consultation metadata.
    """
    industry = meta.industry.title()
    stage = meta.stage.lower()
    goal = meta.goal

    stage_focus = {
        "idea": [
            "Problem validation",
            "Customer discovery",
            "Value proposition",
            "Competitive scan",
        ],
        "mvp": [
            "MVP scope",
            "Success metrics",
            "Go-to-market",
            "Pricing hypothesis",
        ],
        "growth": [
            "Acquisition channels",
            "Retention levers",
            "Unit economics",
            "Sales pipeline",
        ],
        "scale": [
            "Org design",
            "Process/automation",
            "Internationalization",
            "Risk & compliance",
        ],
    }

    focus = stage_focus.get(stage, stage_focus["idea"])  # default to idea

    bullets = "\n".join(
        [
            f"- {topic}: Consider 1-2 experiments this week to validate assumptions."
            for topic in focus
        ]
    )

    next_steps = (
        "1) Define a one-sentence goal for the next 7 days\n"
        "2) Pick one channel to test (e.g., LinkedIn, cold email, partnerships)\n"
        "3) Draft a simple success metric (e.g., 5 qualified leads)\n"
        "4) Schedule a weekly review to iterate"
    )

    return (
        f"Context\n- Industry: {industry}\n- Stage: {stage}\n- Goal: {goal}\n\n"
        f"Your prompt\n" 
        f"- {user_text}\n\n"
        f"Advisor Summary\n"
        f"- Core thesis: Align actions to the next riskiest assumption.\n"
        f"- Focus areas:\n{bullets}\n\n"
        f"Suggested Next Steps\n{next_steps}\n\n"
        f"Metrics To Watch\n- Lead velocity\n- Conversion to qualified opportunity\n- CAC vs LTV\n- Activation time\n\n"
        f"Resources\n- Lean Canvas\n- Mom Test (customer interviews)\n- Pirate Metrics (AARRR)\n"
    )


# -----------------------------
# Routes
# -----------------------------

@app.get("/")
def read_root():
    return {"message": "AI Business Consultant Backend Running"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set"
            response["database_name"] = getattr(db, "name", "✅ Connected")
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


@app.post("/api/consultations", response_model=Consultation)
def create_consultation(payload: ConsultationCreate):
    doc = payload.model_dump()
    inserted_id = create_document("consultation", doc)
    saved = db["consultation"].find_one({"_id": ObjectId(inserted_id)})
    saved_serialized = serialize_doc(saved)
    # map _id to id
    saved_serialized["id"] = saved_serialized.pop("_id")
    return saved_serialized


@app.get("/api/consultations", response_model=List[Consultation])
def list_consultations():
    items = get_documents("consultation", {}, limit=50)
    out = []
    for it in items:
        s = serialize_doc(it)
        s["id"] = s.pop("_id")
        out.append(s)
    return out


@app.get("/api/consultations/{consultation_id}", response_model=Consultation)
def get_consultation(consultation_id: str):
    try:
        it = db["consultation"].find_one({"_id": ObjectId(consultation_id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid consultation id")
    if not it:
        raise HTTPException(status_code=404, detail="Consultation not found")
    s = serialize_doc(it)
    s["id"] = s.pop("_id")
    return s


@app.get("/api/consultations/{consultation_id}/messages", response_model=List[Message])
def list_messages(consultation_id: str):
    try:
        _ = ObjectId(consultation_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid consultation id")
    items = get_documents("message", {"consultation_id": consultation_id}, limit=200)
    out = []
    for it in items:
        s = serialize_doc(it)
        s["id"] = s.pop("_id")
        out.append(s)
    return out


@app.post("/api/consultations/{consultation_id}/messages", response_model=Message)
def send_message(consultation_id: str, payload: MessageIn):
    # Verify consultation exists
    try:
        cons = db["consultation"].find_one({"_id": ObjectId(consultation_id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid consultation id")
    if not cons:
        raise HTTPException(status_code=404, detail="Consultation not found")

    # Store user message
    user_msg = {
        "consultation_id": consultation_id,
        "role": "user",
        "content": payload.content,
    }
    _ = create_document("message", user_msg)

    # Generate advisor reply
    meta = ConsultationCreate(
        business_name=cons.get("business_name", ""),
        industry=cons.get("industry", ""),
        stage=cons.get("stage", "idea"),
        goal=cons.get("goal", ""),
        notes=cons.get("notes"),
    )
    reply_text = generate_advice(payload.content, meta)

    assistant_msg = {
        "consultation_id": consultation_id,
        "role": "assistant",
        "content": reply_text,
    }
    inserted_id = create_document("message", assistant_msg)

    saved = db["message"].find_one({"_id": ObjectId(inserted_id)})
    s = serialize_doc(saved)
    s["id"] = s.pop("_id")
    return s


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
