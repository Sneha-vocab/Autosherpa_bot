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
from conversation_state import conversation_manager
from browse_car_flow import handle_browse_car_flow
from database import car_db

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
    Process incoming text messages with intent extraction and response generation.
    Handles both car-related queries and out-of-context questions gracefully.
    Routes to specific flows (like browse_car) when appropriate.
    """
    try:
        # Check if user is in an active conversation flow
        state = conversation_manager.get_state(from_number)
        if state and state.flow_name == "browse_car":
            # User is in browse car flow, handle it directly
            try:
                response_text = await handle_browse_car_flow(from_number, text, None)
                await send_whatsapp_message(from_number, response_text)
                print(f"Browse car flow response sent to {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error in browse car flow: {flow_exc}")
                # Fall through to normal processing
        
        if state and state.flow_name == "car_valuation":
            # User is in car valuation flow, handle it directly
            try:
                from car_valuation_flow import handle_car_valuation_flow
                response_text = await handle_car_valuation_flow(from_number, text, None)
                await send_whatsapp_message(from_number, response_text)
                print(f"Car valuation flow response sent to {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error in car valuation flow: {flow_exc}")
                # Fall through to normal processing
        
        if state and state.flow_name == "emi":
            # User is in EMI flow, handle it directly
            try:
                from emi_flow import handle_emi_flow
                response_text = await handle_emi_flow(from_number, text, None)
                await send_whatsapp_message(from_number, response_text)
                print(f"EMI flow response sent to {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error in EMI flow: {flow_exc}")
                # Fall through to normal processing
        
        if state and state.flow_name == "service_booking":
            # User is in service booking flow, handle it directly
            try:
                from service_booking_flow import handle_service_booking_flow
                response_text = await handle_service_booking_flow(from_number, text, None)
                await send_whatsapp_message(from_number, response_text)
                print(f"Service booking flow response sent to {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error in service booking flow: {flow_exc}")
                # Fall through to normal processing
        
        # Step 1: Extract intent from the message
        intent_result: IntentResult = await extract_intent(text)
        print("Intent extraction result:")
        print(f"  Intent: {intent_result.intent}")
        print(f"  Summary: {intent_result.summary}")
        print(f"  Confidence: {intent_result.confidence:.2f}")
        if intent_result.entities:
            print(f"  Entities: {intent_result.entities}")
        
        # Step 2: Check for service booking intent
        intent_lower = intent_result.intent.lower()
        text_lower = text.lower()
        
        service_keywords = ["book service", "service booking", "book a service", "service", "servicing", "repair", "maintenance", "book"]
        is_service_intent = (
            "service" in intent_lower or
            "booking" in intent_lower or
            "book" in intent_lower or
            "repair" in intent_lower or
            "servicing" in intent_lower or
            any(keyword in text_lower for keyword in service_keywords)
        )
        
        if is_service_intent:
            # Route to service booking flow
            try:
                from service_booking_flow import handle_service_booking_flow
                response_text = await handle_service_booking_flow(from_number, text, intent_result)
                await send_whatsapp_message(from_number, response_text)
                print(f"Service booking flow initiated for {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error initiating service booking flow: {flow_exc}")
                # Fall through to normal processing
        
        # Step 3: Check for EMI intent
        emi_keywords = ["emi", "loan", "installment", "finance", "down payment", "monthly payment", "monthly emi", "calculate emi"]
        is_emi_intent = (
            "emi" in intent_lower or
            "loan" in intent_lower or
            "installment" in intent_lower or
            "finance" in intent_lower or
            any(keyword in text_lower for keyword in emi_keywords)
        )
        
        if is_emi_intent:
            # Route to EMI flow
            try:
                from emi_flow import handle_emi_flow
                response_text = await handle_emi_flow(from_number, text, intent_result)
                await send_whatsapp_message(from_number, response_text)
                print(f"EMI flow initiated for {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error initiating EMI flow: {flow_exc}")
                # Fall through to normal processing
        
        # Step 4: Check for car_valuation intent
        valuation_keywords = ["value", "valuation", "price", "worth", "resale", "sell", "how much", "estimate", "appraise"]
        is_valuation_intent = (
            "value" in intent_lower or
            "valuation" in intent_lower or
            "price" in intent_lower or
            "worth" in intent_lower or
            any(keyword in text_lower for keyword in valuation_keywords)
        )
        
        if is_valuation_intent:
            # Route to car valuation flow
            try:
                from car_valuation_flow import handle_car_valuation_flow
                response_text = await handle_car_valuation_flow(from_number, text, intent_result)
                await send_whatsapp_message(from_number, response_text)
                print(f"Car valuation flow initiated for {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error initiating car valuation flow: {flow_exc}")
                # Fall through to normal processing
        
        # Step 5: Check for browse_car intent
        browse_keywords = ["browse", "buy", "purchase", "looking for", "want to buy", "search", "find car"]
        is_browse_intent = (
            "browse" in intent_lower or
            "buy" in intent_lower or
            "purchase" in intent_lower or
            any(keyword in text_lower for keyword in browse_keywords)
        )
        
        if is_browse_intent:
            # Route to browse car flow
            try:
                response_text = await handle_browse_car_flow(from_number, text, intent_result)
                await send_whatsapp_message(from_number, response_text)
                print(f"Browse car flow initiated for {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error initiating browse car flow: {flow_exc}")
                # Fall through to normal processing
        
        # Step 6: Determine if the query is car-related
        car_related = is_car_related(intent_result, text)
        print(f"  Car-related: {car_related}")
        
        # Step 7: Generate human-like response based on intent
        try:
            response_text = await generate_response(
                original_message=text,
                intent_result=intent_result,
                is_car_related=car_related
            )
            print(f"Generated response: {response_text}")
            
            # Step 8: Send the response back to the user
            await send_whatsapp_message(from_number, response_text)
            print(f"Response sent to {from_number}")
            
        except ResponseGenerationError as exc:
            print(f"Response generation failed: {exc}")
            # Fallback response for out-of-context questions
            if not car_related:
                fallback = (
                    "I appreciate your question! I'm specifically here to help "
                    "with car-related queries like maintenance, repairs, insurance, "
                    "or vehicle information. How can I assist you with your car today?"
                )
            else:
                fallback = (
                    "I'm having trouble processing that right now. Could you "
                    "please rephrase your car-related question? I'm here to help!"
                )
            await send_whatsapp_message(from_number, fallback)
            print(f"Fallback response sent to {from_number}")
            
    except IntentExtractionError as exc:
        print(f"Intent extraction failed: {exc}")
        # Fallback for intent extraction failures
        fallback = (
            "I'm having some technical difficulties understanding your message. "
            "Could you please rephrase your question about cars? I'm here to help!"
        )
        await send_whatsapp_message(from_number, fallback)
        
    except ValueError as exc:
        print(f"Invalid message for intent extraction: {exc}")
        # Handle empty or invalid messages
        fallback = (
            "I didn't quite catch that. Could you please send me a message "
            "about your car? I'm here to help with car-related questions!"
        )
        await send_whatsapp_message(from_number, fallback)
    
    except Exception as exc:
        print(f"Unexpected error processing message: {exc}")
        import traceback
        traceback.print_exc()
        # Generic fallback for any other errors
        fallback = (
            "I encountered an issue processing your message. Please try again "
            "with a car-related question, and I'll do my best to help!"
        )
        try:
            await send_whatsapp_message(from_number, fallback)
        except Exception as send_exc:
            print(f"Failed to send fallback message: {send_exc}")


async def process_image_message(from_number: str, image_id: str, caption: str, message_id: str):
    """
    Process incoming image messages
    Add your business logic here
    """
    pass


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

