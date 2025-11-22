from fastapi import FastAPI, Request, Response, HTTPException, Header
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import hmac
import hashlib
import os
from typing import Optional
import uvicorn
from dotenv import load_dotenv
from intent_service import (
    IntentExtractionError,
    IntentResult,
    ResponseGenerationError,
    extract_intent,
    generate_response,
    is_car_related,
)
from conversation_state import conversation_manager,ConversationState
from browse_car_flow import handle_browse_car_flow
from database import car_db
from route import llm_route



# Load environment variables
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    # Startup
    if car_db:
        try:
            await car_db.init_schema()
            print("✓ Database schema initialized")
        except Exception as e:
            print(f"⚠ Database initialization error: {e}")
    
    yield
    
    # Shutdown
    if car_db:
        try:
            await car_db.close()
            print("✓ Database connections closed")
        except Exception as e:
            print(f"⚠ Database shutdown error: {e}")


app = FastAPI(title="WhatsApp Webhook API", version="1.0.0", lifespan=lifespan)

# Configuration from environment variables
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "your_verify_token_here")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # For signature verification
APP_SECRET = os.getenv("APP_SECRET", "")  # Meta App Secret


class WhatsAppMessage(BaseModel):
    """Model for incoming WhatsApp messages"""
    pass


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "message": "WhatsApp Webhook API is running"}


@app.get("/webhook")
async def verify_webhook(
    request: Request,
    hub_mode: Optional[str] = None,
    hub_challenge: Optional[str] = None,
    hub_verify_token: Optional[str] = None
 ):
    """
    Webhook verification endpoint
    Meta will call this endpoint to verify your webhook during setup
    """
    # Get query parameters
    mode = hub_mode or request.query_params.get("hub.mode")
    token = hub_verify_token or request.query_params.get("hub.verify_token")
    challenge = hub_challenge or request.query_params.get("hub.challenge")

    # Verify the token
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified successfully!")
        return Response(content=challenge, status_code=200)
    else:
        print(f"Webhook verification failed. Mode: {mode}, Token match: {token == VERIFY_TOKEN}")
        raise HTTPException(status_code=403, detail="Verification failed")


def verify_signature(payload: bytes, signature: str) -> bool:
    """
    Verify the webhook signature from Meta
    This ensures the request is actually from Meta
    """
    if not WEBHOOK_SECRET:
        # If no secret is configured, skip verification (not recommended for production)
        return True
    
    # Calculate expected signature
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # Meta sends signature as "sha256=<hash>"
    received_signature = signature.replace("sha256=", "") if signature else ""
    
    return hmac.compare_digest(expected_signature, received_signature)


@app.post("/webhook")
async def webhook_handler(request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    """
    Main webhook endpoint to receive WhatsApp messages and events
    """
    try:
        # Read the raw body for signature verification
        body = await request.body()
        
        # Verify signature if secret is configured
        if WEBHOOK_SECRET and x_hub_signature_256:
            if not verify_signature(body, x_hub_signature_256):
                print("Invalid webhook signature")
                raise HTTPException(status_code=403, detail="Invalid signature")
        
        # Parse JSON payload
        import json
        data = json.loads(body.decode('utf-8'))
        
        # Handle different types of webhook events
        if "object" in data and data["object"] == "whatsapp_business_account":
            entries = data.get("entry", [])
            
            for entry in entries:
                changes = entry.get("changes", [])
                
                for change in changes:
                    value = change.get("value", {})
                    
                    # Handle status updates (message delivery, read receipts, etc.)
                    if "statuses" in value:
                        statuses = value.get("statuses", [])
                        for status in statuses:
                            await handle_status_update(status)
                    
                    # Handle incoming messages
                    if "messages" in value:
                        messages = value.get("messages", [])
                        for message in messages:
                            await handle_message(message, value.get("metadata", {}))
        
        # Always return 200 to acknowledge receipt
        return JSONResponse(content={"status": "success"}, status_code=200)
    
    except json.JSONDecodeError:
        print("Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        print(f"Error processing webhook: {str(e)}")
        # Still return 200 to prevent Meta from retrying
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=200)


async def handle_message(message: dict, metadata: dict):
    """
    Process incoming WhatsApp messages
    """
    message_id = message.get("id")
    message_type = message.get("type")
    from_number = message.get("from")
    timestamp = message.get("timestamp")
    
    print(f"\n=== New WhatsApp Message ===")
    print(f"Message ID: {message_id}")
    print(f"From: {from_number}")
    print(f"Type: {message_type}")
    print(f"Timestamp: {timestamp}")
    
    # Handle different message types
    if message_type == "text":
        text_body = message.get("text", {}).get("body", "")
        print(f"Text: {text_body}")
        # Add your message processing logic here
        await process_text_message(from_number, text_body, message_id)
    
    elif message_type == "image":
        image = message.get("image", {})
        image_id = image.get("id")
        caption = image.get("caption", "")
        print(f"Image ID: {image_id}")
        print(f"Caption: {caption}")
        # Add your image processing logic here
        await process_image_message(from_number, image_id, caption, message_id)
    
    elif message_type == "video":
        video = message.get("video", {})
        video_id = video.get("id")
        caption = video.get("caption", "")
        print(f"Video ID: {video_id}")
        print(f"Caption: {caption}")
        # Add your video processing logic here
    
    elif message_type == "audio":
        audio = message.get("audio", {})
        audio_id = audio.get("id")
        print(f"Audio ID: {audio_id}")
        # Add your audio processing logic here
    
    elif message_type == "document":
        document = message.get("document", {})
        document_id = document.get("id")
        filename = document.get("filename", "")
        print(f"Document ID: {document_id}")
        print(f"Filename: {filename}")
        # Add your document processing logic here
    
    elif message_type == "location":
        location = message.get("location", {})
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        print(f"Location: {latitude}, {longitude}")
        # Add your location processing logic here
    
    elif message_type == "contacts":
        contacts = message.get("contacts", [])
        print(f"Contacts: {len(contacts)} contact(s)")
        # Add your contacts processing logic here
    
    else:
        print(f"Unsupported message type: {message_type}")
    
    print("=" * 30 + "\n")


async def handle_status_update(status: dict):
    """
    Process message status updates (sent, delivered, read, failed)
    """
    message_id = status.get("id")
    status_type = status.get("status")  # sent, delivered, read, failed
    recipient_id = status.get("recipient_id")
    timestamp = status.get("timestamp")
    
    print(f"\n=== Status Update ===")
    print(f"Message ID: {message_id}")
    print(f"Status: {status_type}")
    print(f"Recipient: {recipient_id}")
    print(f"Timestamp: {timestamp}")
    
    if status_type == "failed":
        error = status.get("errors", [])
        if error:
            print(f"Error: {error[0]}")
    
    print("=" * 20 + "\n")


async def process_text_message(from_number: str, text: str, message_id: str):
    """
    Handles incoming WhatsApp text messages.
    Preserves memory across flows.
    """

    try:
        # STEP 0 — CHECK IF USER IS ALREADY IN A FLOW
        state = conversation_manager.get_state(from_number)
        if state:
            flow = state.flow_name
            try:
                if flow == "browse_used_cars":
                    response = await handle_browse_car_flow(from_number, text)
                elif flow == "car_validation":
                    from car_validation_flow import handle_car_validation_flow
                    response = await handle_car_validation_flow(from_number, text)
                elif flow == "emi_options":
                    from emi_flow import handle_emi_flow
                    response = await handle_emi_flow(from_number, text)
                elif flow == "service_booking":
                    from service_booking_flow import handle_service_booking_flow
                    response = await handle_service_booking_flow(from_number, text)
                else:
                    response = None

                if response:
                    await send_whatsapp_message(from_number, response)
                    return

            except Exception as exc:
                print(f"[FLOW ERROR] Error inside {flow}: {exc}")
                # fallback to LLM routing

        # STEP 1 — RUN LLM ROUTER
        route = await llm_route(text)
        intent = route["intent"]
        confidence = route["confidence"]

        print(f"Intent routing result: Intent={intent}, Confidence={confidence}")

        # STEP 2 — MAP INTENT TO FLOW
        FLOW_MAP = {
            "browse_used_cars": "browse_used_cars",
            "car_validation": "car_validation",
            "emi_options": "emi_options",
            "service_booking": "service_booking",
        }
        mapped_flow = FLOW_MAP.get(intent)

        if mapped_flow:
            # Use existing state if available, else initialize safely
            state = conversation_manager.get_state(from_number)
            if state:
                # update flow and step, keep existing data
                state.flow_name = mapped_flow
                state.step = "start"
                conversation_manager.set_state(from_number, state)
            else:
                # first time
                conversation_manager.set_state(
                    from_number,
                    ConversationState(
                        user_id=from_number,
                        flow_name=mapped_flow,
                        step="start",
                        data={}  # first initialization only
                    )
                )

            # Dispatch to flow handler
            if mapped_flow == "browse_used_cars":
                response = await handle_browse_car_flow(from_number, text)
            elif mapped_flow == "car_validation":
                from car_validation_flow import handle_car_validation_flow
                response = await handle_car_validation_flow(from_number, text)
            elif mapped_flow == "emi_options":
                from emi_flow import handle_emi_flow
                response = await handle_emi_flow(from_number, text)
            elif mapped_flow == "service_booking":
                from service_booking_flow import handle_service_booking_flow
                response = await handle_service_booking_flow(from_number, text)

            await send_whatsapp_message(from_number, response)
            return

        # STEP 3 — NORMAL / SMALL TALK
        response = await handle_normal_intent(text)
        await send_whatsapp_message(from_number, response)

    except Exception as exc:
        print(f"[FATAL ERROR] {exc}")
        fallback = "Something went wrong, but I'm here to help with your car! 🚗"
        await send_whatsapp_message(from_number, fallback)


async def process_image_message(from_number: str, image_id: str, caption: str, message_id: str):
    """
    Process incoming image messages
    Add your business logic here
    """
    pass


async def handle_normal_intent(text: str) -> str:

    prompt = f"""
    You are AutoSherpa, a friendly car assistant.

    If the user's message is a greeting:
    - Respond warmly
    - Then gently guide them to ask something car-related
    - Keep response under 15 words

    If the message is unrelated to cars:
    - Politely acknowledge it
    - Then guide them back to car-related topics
    - Keep it under 10-15 words

    User message: "{text}"
    """

    import httpx, os
    api_key = os.getenv("GOOGLE_API_KEY")
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    response = httpx.post(
        url,
        params={"key": api_key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=8,
    )

    return response.json()["candidates"][0]["content"]["parts"][0]["text"]


# Optional: Helper function to send WhatsApp messages via Meta API
async def send_whatsapp_message(
    to: str,
    message: str,
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None
 ):
    """
    Send a WhatsApp message using Meta's API
    This is a helper function - you'll need to implement the actual API call
    """
    import httpx
    
    phone_number_id = phone_number_id or os.getenv("PHONE_NUMBER_ID")
    access_token = access_token or os.getenv("ACCESS_TOKEN")
    
    if not phone_number_id or not access_token:
        print("Missing phone_number_id or access_token")
        return
    
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            print(f"Message sent successfully: {response.json()}")
            return response.json()
    except httpx.HTTPError as e:
        print(f"Error sending message: {e}")
        raise


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

