"""Intelligent message analysis for EMI flow using Gemini LLM."""

import os
import json
import httpx
from typing import Optional, Dict, Any
from intent_service import ResponseGenerationError, DEFAULT_GEMINI_MODEL

_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class EMIAnalysisError(RuntimeError):
    """Raised when EMI analysis fails."""


async def analyze_emi_message(
    message: str,
    conversation_context: Dict[str, Any],
    available_brands: list,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Analyze user message in the context of EMI flow.
    
    Returns:
        {
            "extracted_car_id": int or None,
            "extracted_down_payment": float or None,
            "extracted_tenure": int or None,
            "user_intent": str,
            "needs_clarification": bool,
            "clarification_question": str or None,
        }
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise EMIAnalysisError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    # Build context
    current_step = conversation_context.get("step", "selecting_car")
    selected_car = conversation_context.get("data", {}).get("selected_car")
    down_payment = conversation_context.get("data", {}).get("down_payment")
    tenure = conversation_context.get("data", {}).get("tenure")
    
    context_info = f"""
Current conversation state:
- Step: {current_step}
- Selected car: {selected_car}
- Down payment: {down_payment}
- Tenure: {tenure} months
"""
    
    prompt = f"""You are an intelligent car finance assistant helping a customer calculate EMI for a car purchase. Analyze the user's message and extract relevant information.

{context_info}

User's message: "{message}"

Analyze this message and extract:
1. Car selection (if mentioned as a number like 1, 2, 3)
2. Down payment amount (if mentioned) - extract in rupees or lakhs. Convert lakhs to rupees (1 lakh = 100000)
3. Loan tenure (if mentioned) - extract in months (e.g., "12 months", "2 years" = 24 months, "36 months")
4. User's intent - what is the user trying to do? (e.g., "selecting_car", "providing_down_payment", "selecting_tenure", "asking_question", "changing_criteria")
5. Whether clarification is needed
6. If clarification needed, what question to ask

Return your analysis as JSON with these exact keys:
{{
    "extracted_car_id": number_or_null,
    "extracted_down_payment": number_or_null,
    "extracted_tenure": number_or_null,
    "user_intent": "intent_string",
    "needs_clarification": true_or_false,
    "clarification_question": "question_or_null",
    "confidence": 0.0_to_1.0
}}

Important:
- Down payment should be in rupees (convert from lakhs if needed)
- Tenure should be in months (convert from years if needed: 1 year = 12 months, 2 years = 24 months, etc.)
- If user says "change" or "different", intent is "changing_criteria"
- If user provides a number (1, 2, 3), it could be car selection or tenure - use context to determine
- Be smart about understanding user's intent even if they don't use exact words
"""
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "topP": 0.9,
            "topK": 32,
            "responseMimeType": "application/json",
        },
    }
    
    request_context = {
        "method": "POST",
        "url": url,
        "params": {"key": api_key},
        "headers": {"Content-Type": "application/json"},
        "json": payload,
        "timeout": timeout,
    }
    
    try:
        if client:
            response = await client.request(**request_context)
        else:
            async with httpx.AsyncClient() as local_client:
                response = await local_client.request(**request_context)
    except httpx.RequestError as exc:
        raise EMIAnalysisError("Failed to reach Gemini API") from exc
    
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise EMIAnalysisError(
            f"Gemini API request failed with status {exc.response.status_code}"
        ) from exc
    
    payload = response.json()
    try:
        candidate_text = (
            payload["candidates"][0]["content"]["parts"][0]["text"]
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise EMIAnalysisError(
            "Gemini API returned an unexpected response structure"
        ) from exc
    
    try:
        parsed = json.loads(candidate_text)
        
        return {
            "extracted_car_id": parsed.get("extracted_car_id"),
            "extracted_down_payment": parsed.get("extracted_down_payment"),
            "extracted_tenure": parsed.get("extracted_tenure"),
            "user_intent": parsed.get("user_intent", "unknown"),
            "needs_clarification": parsed.get("needs_clarification", False),
            "clarification_question": parsed.get("clarification_question"),
            "confidence": parsed.get("confidence", 0.0),
        }
    except json.JSONDecodeError as exc:
        raise EMIAnalysisError("Failed to parse Gemini response as JSON") from exc


async def generate_emi_response(
    message: str,
    conversation_context: Dict[str, Any],
    analysis_result: Dict[str, Any],
    available_brands: list,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Generate a human-like, contextual response for the EMI flow."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ResponseGenerationError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    current_step = conversation_context.get("step", "selecting_car")
    selected_car = conversation_context.get("data", {}).get("selected_car")
    down_payment = conversation_context.get("data", {}).get("down_payment")
    tenure = conversation_context.get("data", {}).get("tenure")
    
    # Build context-aware prompt
    if current_step == "selecting_car":
        system_prompt = f"""You are a friendly and professional car finance assistant helping a customer calculate EMI.

Current situation:
- You're helping them select a car for EMI calculation
- Available brands: {', '.join(available_brands)}

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
1. Acknowledge what the user said in a warm, human way
2. Guide them to select a car or browse cars
3. Be conversational, friendly, and helpful
4. Keep it brief (2-3 sentences max)
5. Use emojis sparingly but naturally

Generate a natural, human-like response:"""
    
    elif current_step == "down_payment":
        car_info = f"{selected_car.get('brand', '')} {selected_car.get('model', '')}" if selected_car else "selected car"
        system_prompt = f"""You are a friendly car finance assistant helping with down payment.

Current situation:
- Car selected: {car_info}
- Car price: ₹{selected_car.get('price', 0):,.0f} if selected_car else 'Not available'

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
- If they provided down payment, confirm it enthusiastically
- If not, ask for down payment amount naturally
- Be warm, professional, and human-like
- Keep it brief (2-3 sentences max)

Generate a natural response:"""
    
    elif current_step == "selecting_tenure":
        system_prompt = f"""You are a friendly car finance assistant helping select loan tenure.

Current situation:
- Down payment: ₹{down_payment:,.0f} if down_payment else 'Not set'

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
- If they selected tenure, acknowledge it
- If not, guide them to select a tenure option
- Be warm and professional
- Keep it brief (2-3 sentences max)

Generate a natural response:"""
    
    else:
        system_prompt = f"""You are a friendly car finance assistant. User said: "{message}". Respond naturally and helpfully."""
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": system_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 200,
        },
    }
    
    request_context = {
        "method": "POST",
        "url": url,
        "params": {"key": api_key},
        "headers": {"Content-Type": "application/json"},
        "json": payload,
        "timeout": timeout,
    }
    
    try:
        if client:
            response = await client.request(**request_context)
        else:
            async with httpx.AsyncClient() as local_client:
                response = await local_client.request(**request_context)
    except httpx.RequestError as exc:
        raise ResponseGenerationError("Failed to reach Gemini API") from exc
    
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ResponseGenerationError(
            f"Gemini API request failed with status {exc.response.status_code}"
        ) from exc
    
    payload = response.json()
    try:
        generated_text = (
            payload["candidates"][0]["content"]["parts"][0]["text"]
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ResponseGenerationError(
            "Gemini API returned an unexpected response structure"
        ) from exc
    
    return generated_text

