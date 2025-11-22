import os
import json
import httpx
from typing import Optional, Dict, Any

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

class RoutingError(RuntimeError):
    pass


async def llm_route(
    message: str,
    *,
    model: Optional[str] = None,
    timeout: float = 10.0,
    client: Optional[httpx.AsyncClient] = None,
 ) -> Dict[str, Any]:
    """
    PURE LLM ROUTER — decides which flow to switch to.
    Output always STRICT JSON:
    {
        "intent": "browse_used_cars | car_validation | emi_options | service_booking | normal",
        "confidence": 0.xx
    }
    """

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RoutingError("GOOGLE_API_KEY missing")

    resolved_model = model or DEFAULT_GEMINI_MODEL
    url = _API_URL_TEMPLATE.format(model=resolved_model)

    prompt = f"""
    You are the **central intent router for AutoSherpa**, an AI assistant that helps users
    with car-related tasks. Your job is to analyze the user's message deeply and classify it
    into exactly ONE domain.

    1. **browse_used_cars**
    User is trying to explore cars, compare options, or filter/search based on:
    - budget (e.g., “cars under 5 lakh”, “my budget is 10k”)
    - body type: SUV, sedan, hatchback, coupe, EV, hybrid
    - brand/make: Tata, Honda, Ford, Toyota, BMW
    - model: Swift, Creta, Alto, City
    - purpose: family car, daily commute, long drive
    - year, mileage, fuel type
    - asking “show”, “recommend”, “suggest”
    Example messages:
    - “Show me used SUVs under 8 lakh”
    - “Which is better: Swift or Baleno?”
    - “I want a good family car in budget”
    - “Looking for a second-hand EV”

    2. **car_validation**
    User wants to verify a car, confirm model details, or validate authenticity.
    They may ask:
    - is this model good?
    - does this variant exist?
    - is 2014 Alto VXI legit?
    - check car condition/history
    - compare the correctness of model names
    Example messages:
    - “Is Creta 1.6 SX 2017 real or fake?”
    - “Check if Honda City 2015 VMT exists”
    - “How to know if a used car is accidental?”

    3. **emi_options**
    User wants financing, EMI, loans, or cost breakdown.
    Includes:
    - EMI per month
    - down payment
    - loan duration
    - interest rate
    - finance advice
    Example messages:
    - “What will be EMI for a 6 lakh car for 5 years?”
    - “Loan options for used cars?”
    - “How much monthly if I buy a Swift?”

    4. **service_booking**
    User wants to book/ask about servicing or repairs.
    Includes:
    - schedule appointment
    - service center
    - maintenance request
    - oil change, brake change, inspection
    - breakdown help
    Example messages:
    - “I want to book service for my car”
    - “My brakes make noise, need repair”
    - “Where can I get my Honda serviced tomorrow?”

    5. **normal**
    Anything that does NOT belong to the above.
    Includes:
    - Greetings: hi, hello, gm, sup
    - Casual chat
    - Out-of-context questions
    - Emotional expressions (“I’m bored”)
    - Meta statements (“who are you?”)
    Example messages:
    - “Hey there”
    - “What is the weather?”
    - “Tell me a joke”
    - “Who built you?”

    - If the message contains BOTH buying intent AND validation questions:
        → choose **browse_used_cars** (main goal = purchase).
    
    - If user expresses confusion (“which car is original?”, “is this model real?”)
        → choose **car_validation**.

    - If the message contains the words:
        - “EMI”, “loan”, “monthly”, “interest”, “finance”
        → immediate **emi_options**.

    - If the message contains:
        - “service”, “repair”, “mechanic”, “fix”, “issue”, “problem”
        → choose **service_booking**.

    - If multiple categories could apply, STRICT PRIORITY ORDER:
        1) service_booking  
        2) emi_options  
        3) car_validation  
        4) browse_used_cars  
        5) normal  

    - If truly unsure → return **normal**.



    {{
    "intent": "browse_used_cars | car_validation | emi_options | service_booking | normal",
    "confidence": 0.xx
    }}

    NO explanations. NO prose. JSON ONLY.

    User message: "{message}"
    """

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "topK": 32,
            "responseMimeType": "application/json",
        },
    }

    request_args = {
        "method": "POST",
        "url": url,
        "params": {"key": api_key},
        "headers": {"Content-Type": "application/json"},
        "json": payload,
        "timeout": timeout,
    }

    try:
        if client:
            resp = await client.request(**request_args)
        else:
            async with httpx.AsyncClient() as c:
                resp = await c.request(**request_args)
        resp.raise_for_status()

        raw = resp.json()
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)

        return {
            "intent": result.get("intent", "normal"),
            "confidence": float(result.get("confidence", 0)),
        }

    except Exception as exc:
        raise RoutingError(f"Routing failed: {str(exc)}")
