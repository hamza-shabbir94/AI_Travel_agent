"""FastAPI backend for the AI Travel Advisor.

Run locally:  python -m uvicorn index:app --reload     (docs: http://localhost:8000/docs)
On Vercel:    detected automatically (a FastAPI `app` in index.py)
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError
from pydantic import BaseModel, Field

import advisor

app = FastAPI(title="AI Travel Advisor API")

# CORS: which websites may call this API from the browser.
# FRONTEND_URL is set on Vercel; "*" (everyone) is the default for local testing.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("FRONTEND_URL", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    """What the frontend sends."""
    message: str = Field(min_length=1, max_length=2000)
    previous_response_id: str | None = None
    generate_image: bool = True


class ChatResponse(BaseModel):
    """What the frontend gets back."""
    answer: str
    response_id: str | None      # send this back with the next message
    is_plan: bool
    image: str | None            # "data:image/png;base64,..." or None
    steps: list[str]             # tools the agent used, e.g. "Searched the web"
    cost_usd: float              # estimated cost of THIS request


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message must not be blank.")

    tracker = advisor.UsageTracker(advisor.MODEL)
    steps = []

    def on_step(name, detail=""):
        steps.append(advisor.STEP_LABELS.get(name, name))

    try:
        reply = advisor.chat(
            message,
            tracker,
            previous_response_id=request.previous_response_id,
            on_step=on_step,
            generate_images=request.generate_image,
        )
    except OpenAIError as error:
        raise HTTPException(
            status_code=502,
            detail="The AI provider could not process the request.",
        ) from error

    return ChatResponse(
        answer=reply.text,
        response_id=reply.response_id,
        is_plan=reply.is_plan,
        image=reply.image,
        steps=steps,
        cost_usd=round(tracker.cost_usd(), 6),
    )
