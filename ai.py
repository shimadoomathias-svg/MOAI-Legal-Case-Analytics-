import os
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/ai", tags=["AI"])

class ExplainRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    findings: str = Field(default="", max_length=8000)

@router.get("/status")
def ai_status():
    return {
        "provider": "OpenRouter",
        "configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "model": os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        "free_only": True
    }

@router.post("/explain")
async def explain_findings(payload: ExplainRequest):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OpenRouter is not configured. Core analytics remain available.")
    model = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    if not (model == "openrouter/free" or model.endswith(":free")):
        raise HTTPException(status_code=500, detail="Only OpenRouter free models are permitted by this application.")
    prompt = (
        "You assist legal researchers by explaining supplied aggregate or anonymised research findings. "
        "Do not invent authorities, cases, laws, or statistics. State limitations. Do not provide legal advice "
        "or predict a guaranteed court outcome. If information is insufficient, say so.\n\n"
        f"Research question:\n{payload.question}\n\nFindings:\n{payload.findings}"
    )
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": os.getenv("APP_PUBLIC_URL", "https://moai-legal-case-analytics.onrender.com"),
                    "X-Title": "MOAI Legal Case Analytics",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="The free AI request limit may have been reached. Try again later.")
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="The free AI provider is temporarily unavailable. Core analytics remain available.")
        data = response.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not answer:
            raise HTTPException(status_code=502, detail="The AI provider returned no explanation.")
        return {"answer": answer, "model": data.get("model", model), "provider": "OpenRouter"}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="The AI request timed out. Please try again.")
