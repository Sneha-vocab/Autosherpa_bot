"""Intelligent message analysis for car valuation flow using Gemini LLM."""

import os
import json
import httpx
from typing import Optional, Dict, Any
from intent_service import ResponseGenerationError, DEFAULT_GEMINI_MODEL

_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class CarValuationAnalysisError(RuntimeError):
    """Raised when car valuation analysis fails."""


async def analyze_valuation_message(
    message: str,
    conversation_context: Dict[str, Any],
    available_brands: list,
    available_fuel_types: list,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Analyze user message in the context of car valuation flow.
    
    Returns:
        {
            "extracted_brand": str or None,
            "extracted_model": str or None,
            "extracted_year": int or None,
            "extracted_fuel_type": str or None,
            "extracted_condition": str or None,
            "user_intent": str,
            "needs_clarification": bool,
            "clarification_question": str or None,
        }
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise CarValuationAnalysisError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    # Build context
    current_step = conversation_context.get("step", "collecting_info")
    collected_brand = conversation_context.get("data", {}).get("brand")
    collected_model = conversation_context.get("data", {}).get("model")
    collected_year = conversation_context.get("data", {}).get("year")
    collected_fuel_type = conversation_context.get("data", {}).get("fuel_type")
    collected_condition = conversation_context.get("data", {}).get("condition")
    
    context_info = f"""
Current conversation state:
- Step: {current_step}
- Already collected: Brand={collected_brand}, Model={collected_model}, Year={collected_year}, Fuel Type={collected_fuel_type}, Condition={collected_condition}
- Available brands in database: {', '.join(available_brands)}
- Available fuel types: {', '.join(available_fuel_types)}
"""
    
    prompt = f"""You are an intelligent car valuation assistant helping a customer get their car valued. Analyze the user's message and extract relevant information.

{context_info}

User's message: "{message}"

Analyze this message and extract:
1. Brand name (if mentioned) - must match one of the available brands exactly (case-insensitive)
2. Model name (if mentioned) - extract the car model name
3. Year of manufacturing (if mentioned) - extract as a 4-digit year (e.g., 2020, 2018)
4. Fuel type (if mentioned) - must match one of: {', '.join(available_fuel_types)} (case-insensitive)
5. Condition (if mentioned) - extract condition like "excellent", "good", "fair", "poor", "very good", "average"
6. User's intent - what is the user trying to do? (e.g., "providing_brand", "providing_model", "providing_year", "providing_fuel_type", "providing_condition", "asking_question", "changing_criteria")
7. Whether clarification is needed
8. If clarification needed, what question to ask

Return your analysis as JSON with these exact keys:
{{
    "extracted_brand": "brand_name_or_null",
    "extracted_model": "model_name_or_null",
    "extracted_year": number_or_null,
    "extracted_fuel_type": "fuel_type_or_null",
    "extracted_condition": "condition_or_null",
    "user_intent": "intent_string",
    "needs_clarification": true_or_false,
    "clarification_question": "question_or_null",
    "confidence": 0.0_to_1.0
}}

Important:
- Brand must exactly match one from: {available_brands}
- Fuel type must match one from: {available_fuel_types}
- Year should be between 1990 and current year
- Condition should be one of: excellent, very good, good, average, fair, poor
- If user says "change" or "different", intent is "changing_criteria"
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
        raise CarValuationAnalysisError("Failed to reach Gemini API") from exc
    
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise CarValuationAnalysisError(
            f"Gemini API request failed with status {exc.response.status_code}"
        ) from exc
    
    payload = response.json()
    try:
        candidate_text = (
            payload["candidates"][0]["content"]["parts"][0]["text"]
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise CarValuationAnalysisError(
            "Gemini API returned an unexpected response structure"
        ) from exc
    
    try:
        parsed = json.loads(candidate_text)
        
        return {
            "extracted_brand": parsed.get("extracted_brand"),
            "extracted_model": parsed.get("extracted_model"),
            "extracted_year": parsed.get("extracted_year"),
            "extracted_fuel_type": parsed.get("extracted_fuel_type"),
            "extracted_condition": parsed.get("extracted_condition"),
            "user_intent": parsed.get("user_intent", "unknown"),
            "needs_clarification": parsed.get("needs_clarification", False),
            "clarification_question": parsed.get("clarification_question"),
            "confidence": parsed.get("confidence", 0.0),
        }
    except json.JSONDecodeError as exc:
        raise CarValuationAnalysisError("Failed to parse Gemini response as JSON") from exc


async def generate_valuation_response(
    message: str,
    conversation_context: Dict[str, Any],
    analysis_result: Dict[str, Any],
    available_brands: list,
    available_fuel_types: list,
    *,
    model: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Generate a human-like, contextual response for the car valuation flow."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ResponseGenerationError("GOOGLE_API_KEY is not configured")
    
    resolved_model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = _API_URL_TEMPLATE.format(model=resolved_model)
    
    current_step = conversation_context.get("step", "collecting_info")
    collected_brand = conversation_context.get("data", {}).get("brand")
    collected_model = conversation_context.get("data", {}).get("model")
    collected_year = conversation_context.get("data", {}).get("year")
    collected_fuel_type = conversation_context.get("data", {}).get("fuel_type")
    collected_condition = conversation_context.get("data", {}).get("condition")
    
    # Build context-aware prompt
    if current_step == "collecting_info":
        system_prompt = f"""You are a friendly and professional car valuation assistant helping a customer get their car valued.

Current situation:
- You're collecting information: Brand, Model, Year, Fuel Type, and Condition
- Already collected: Brand={collected_brand or 'Not yet'}, Model={collected_model or 'Not yet'}, Year={collected_year or 'Not yet'}, Fuel Type={collected_fuel_type or 'Not yet'}, Condition={collected_condition or 'Not yet'}
- Available brands: {', '.join(available_brands)}
- Available fuel types: {', '.join(available_fuel_types)}

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
1. Acknowledge what the user said in a warm, human way
2. If they provided information (brand/model/year/fuel/condition), confirm it enthusiastically
3. Ask for the NEXT missing piece of information naturally
4. Be conversational, friendly, and helpful - like a real car valuation expert
5. Keep it brief (2-3 sentences max)
6. Use emojis sparingly but naturally

Generate a natural, human-like response:"""
    
    elif current_step == "showing_valuation":
        system_prompt = f"""You are a friendly car valuation assistant showing valuation results.

User's message: "{message}"
Analysis: {analysis_result['user_intent']}

Your task:
- If they want to value another car, be helpful and supportive
- If they have questions, answer them clearly
- Be warm, professional, and human-like
- Keep it brief (2-3 sentences max)

Generate a natural response:"""
    
    else:
        system_prompt = f"""You are a friendly car valuation assistant. User said: "{message}". Respond naturally and helpfully."""
    
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

