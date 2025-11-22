from fastapi import FastAPI, Request, Response, HTTPException, Header
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import hmac
import hashlib
import os
from typing import Optional, Any
import uvicorn
import asyncio
from dotenv import load_dotenv
from intent_service import (
    IntentExtractionError,
    IntentResult,
    ResponseGenerationError,
    FlowRoutingError,
    extract_intent,
    generate_response,
    is_car_related,
    is_car_related_llm,
    route_to_flow,
)
from conversation_state import conversation_manager, detect_flow_switch, is_short_response
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
        print(f"📥 RECEIVED MESSAGE: {text_body}")
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


# Valid flow names
VALID_FLOWS = ["browse_car", "emi", "car_valuation", "service_booking"]

# Timeout for flow handlers (in seconds)
FLOW_HANDLER_TIMEOUT = 30.0  # 30 seconds timeout for flow handlers


def validate_and_sanitize_response(response_text: Optional[str]) -> str:
    """Validate and sanitize response text before sending.
    
    Args:
        response_text: The response text to validate (may be None or empty)
    
    Returns:
        A valid, non-empty response string. Returns a fallback message if input is invalid.
    """
    if not response_text:
        return (
            "I encountered an issue processing your request. "
            "Please try again with a clear message."
        )
    
    # Strip whitespace and check if empty
    sanitized = response_text.strip()
    if not sanitized:
        return (
            "I encountered an issue processing your request. "
            "Please try again with a clear message."
        )
    
    # Ensure message is not too long (WhatsApp limit is 4096 characters)
    if len(sanitized) > 4096:
        print(f"Warning: Response text too long ({len(sanitized)} chars), truncating to 4096")
        sanitized = sanitized[:4093] + "..."
    
    return sanitized


async def call_flow_handler_with_timeout(
    handler_func,
    *args,
    timeout: float = FLOW_HANDLER_TIMEOUT,
    **kwargs
) -> str:
    """Call a flow handler with timeout protection.
    
    Args:
        handler_func: The flow handler function to call
        *args: Positional arguments for the handler
        timeout: Timeout in seconds (default: FLOW_HANDLER_TIMEOUT)
        **kwargs: Keyword arguments for the handler
    
    Returns:
        Response text from the handler, or timeout error message
    """
    try:
        response = await asyncio.wait_for(
            handler_func(*args, **kwargs),
            timeout=timeout
        )
        return response
    except asyncio.TimeoutError:
        print(f"Flow handler timed out after {timeout} seconds")
        return (
            "I'm taking longer than expected to process your request. "
            "Please try again in a moment, or contact us directly if the issue persists."
        )
    except Exception as e:
        print(f"Error in flow handler: {e}")
        raise


async def handle_flow_switch_marker(
    response_text: str,
    from_number: str,
    text: str,
    intent_result: Any,
    current_flow: Optional[str] = None,
    depth: int = 0,
    max_depth: int = 2
) -> Optional[str]:
    """Handle flow switch marker and route to target flow.
    
    Args:
        response_text: The response text that may contain a flow switch marker
        from_number: User's phone number
        text: Original message text
        intent_result: Intent extraction result
        current_flow: Current flow name to prevent self-switching
    
    Returns:
        Updated response text, or None if no switch marker found
    """
    if not response_text or not response_text.startswith("__FLOW_SWITCH__:"):
        return None
    
    try:
        parts = response_text.split(":")
        if len(parts) < 2:
            print(f"Warning: Malformed flow switch marker: {response_text}")
            return "I'm having trouble switching flows. Please try again with a clear request."
        
        target_flow = parts[1].strip()
        
        # Validate target flow
        if target_flow not in VALID_FLOWS:
            print(f"Warning: Invalid flow switch target: {target_flow}")
            return "I'm having trouble switching flows. Please try again with a clear request."
        
        # Prevent self-switching
        if target_flow == current_flow:
            print(f"Warning: Self-referential flow switch detected: {target_flow}")
            return "I'm having trouble switching flows. Please try again with a clear request."
        
        # Route to target flow with timeout protection
        if target_flow == "browse_car":
            return await call_flow_handler_with_timeout(
                handle_browse_car_flow, from_number, text, intent_result
            )
        elif target_flow == "emi":
            from emi_flow import handle_emi_flow
            return await call_flow_handler_with_timeout(
                handle_emi_flow, from_number, text, intent_result
            )
        elif target_flow == "car_valuation":
            from car_valuation_flow import handle_car_valuation_flow
            return await call_flow_handler_with_timeout(
                handle_car_valuation_flow, from_number, text, intent_result
            )
        elif target_flow == "service_booking":
            from service_booking_flow import handle_service_booking_flow
            return await call_flow_handler_with_timeout(
                handle_service_booking_flow, from_number, text, intent_result
            )
        
    except Exception as e:
        print(f"Error handling flow switch marker: {e}")
        return "I'm having trouble switching flows. Please try again with a clear request."
    
    return None


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
    Supports flow switching during conversations.
    """
    try:
        # Check for "change" keyword first - if user is in a flow, handle it in that flow
        state = conversation_manager.get_state(from_number)
        if state and state.flow_name:
            message_lower = text.lower().strip()
            if message_lower == "change" or message_lower == "modify":
                # User wants to change criteria in current flow - let the flow handle it
                # Don't extract intent, just route to current flow
                if state.flow_name == "browse_car":
                    response_text = await call_flow_handler_with_timeout(
                        handle_browse_car_flow, from_number, text, None
                    )
                    await send_whatsapp_message(from_number, response_text)
                    return
                elif state.flow_name == "car_valuation":
                    from car_valuation_flow import handle_car_valuation_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_car_valuation_flow, from_number, text, None
                    )
                    await send_whatsapp_message(from_number, response_text)
                    return
                elif state.flow_name == "emi":
                    from emi_flow import handle_emi_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_emi_flow, from_number, text, None
                    )
                    await send_whatsapp_message(from_number, response_text)
                    return
                elif state.flow_name == "service_booking":
                    from service_booking_flow import handle_service_booking_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_service_booking_flow, from_number, text, None
                    )
                    await send_whatsapp_message(from_number, response_text)
                    return
        
        # Check for "No" - if user is in a flow, handle it contextually
        if state and state.flow_name:
            message_lower = text.lower().strip()
            if message_lower == "no" or message_lower == "nope":
                # User said "No" - this is likely a response to a question
                # Don't reset context, let the flow handle it
                if state.flow_name == "browse_car":
                    # Create a minimal intent result for "no"
                    class NoIntent:
                        intent = "negative_response"
                        confidence = 0.8
                        entities = {}
                    no_intent = NoIntent()
                    response_text = await call_flow_handler_with_timeout(
                        handle_browse_car_flow, from_number, text, no_intent
                    )
                    await send_whatsapp_message(from_number, response_text)
                    return
                elif state.flow_name == "car_valuation":
                    from car_valuation_flow import handle_car_valuation_flow
                    class NoIntent:
                        intent = "negative_response"
                        summary = "User responded with no"
                        confidence = 0.8
                        entities = {}
                    no_intent = NoIntent()
                    response_text = await call_flow_handler_with_timeout(
                        handle_car_valuation_flow, from_number, text, no_intent
                    )
                    await send_whatsapp_message(from_number, response_text)
                    return
                elif state.flow_name == "emi":
                    from emi_flow import handle_emi_flow
                    class NoIntent:
                        intent = "negative_response"
                        summary = "User responded with no"
                        confidence = 0.8
                        entities = {}
                    no_intent = NoIntent()
                    response_text = await call_flow_handler_with_timeout(
                        handle_emi_flow, from_number, text, no_intent
                    )
                    await send_whatsapp_message(from_number, response_text)
                    return
                elif state.flow_name == "service_booking":
                    from service_booking_flow import handle_service_booking_flow
                    class NoIntent:
                        intent = "negative_response"
                        summary = "User responded with no"
                        confidence = 0.8
                        entities = {}
                    no_intent = NoIntent()
                    response_text = await call_flow_handler_with_timeout(
                        handle_service_booking_flow, from_number, text, no_intent
                    )
                    await send_whatsapp_message(from_number, response_text)
                    return
        
        # Step 1: Get current state BEFORE extracting intent (so we can pass flow context)
        state = conversation_manager.get_state(from_number)
        current_flow = state.flow_name if state else None
        current_step = state.step if state else None
        
        # Get conversation context for better intent understanding
        conversation_context = conversation_manager.get_recent_context(from_number, max_exchanges=3)
        
        # Step 2: Check if we're awaiting intent confirmation
        if state and state.data.get("awaiting_intent_confirmation", False):
            # User is responding to an intent clarification question
            original_message = state.data.get("pending_intent_message")
            original_intent = state.data.get("pending_intent")
            
            print(f"🔵 [intent_confirmation] User responding to clarification. Original: '{original_message}', Original intent: {original_intent}")
            
            # Re-extract intent from user's confirmation/clarification
            # User might be confirming, providing more context, or clarifying
            intent_result: IntentResult = await extract_intent(
                text,
                conversation_context=f"Previous message: {original_message}\nUser intent was unclear. User is now clarifying or confirming.",
                current_flow=current_flow,
                current_step=current_step
            )
            
            print(f"🔵 [intent_confirmation] Re-extracted intent: {intent_result.intent}, confidence: {intent_result.confidence:.2f}")
            
            # Clear confirmation flag
            conversation_manager.update_data(
                from_number,
                awaiting_intent_confirmation=False,
                pending_intent_message=None,
                pending_intent=None
            )
            
            # Continue with the new intent result for dynamic routing
            print("Intent extraction result (after confirmation):")
            print(f"  Intent: {intent_result.intent}")
            print(f"  Confidence: {intent_result.confidence:.2f}")
            if intent_result.entities:
                print(f"  Entities: {intent_result.entities}")
        else:
            # Step 2: Extract intent from the message with flow context to avoid false flow switches
            intent_result: IntentResult = await extract_intent(
                text,
                conversation_context=conversation_context if conversation_context else None,
                current_flow=current_flow,
                current_step=current_step
            )
            print("Intent extraction result:")
            print(f"  Intent: {intent_result.intent}")
            print(f"  Confidence: {intent_result.confidence:.2f}")
            if intent_result.entities:
                print(f"  Entities: {intent_result.entities}")
            
            # Check if LLM is confused (low confidence or unclear intent)
            CONFIDENCE_THRESHOLD = 0.7
            UNCLEAR_INTENTS = ["unknown", "unclear", "ambiguous", "unsure"]
            
            is_confused = (
                intent_result.confidence < CONFIDENCE_THRESHOLD or
                intent_result.intent.lower() in UNCLEAR_INTENTS or
                (intent_result.intent.lower() == "unknown" and not intent_result.entities)
            )
            
            if is_confused and not current_flow:
                # LLM is confused and user is not in a flow - ask for clarification
                print(f"⚠️ [intent_confirmation] LLM confused (confidence: {intent_result.confidence:.2f}, intent: {intent_result.intent})")
                
                # Store original message and intent for later
                conversation_manager.update_data(
                    from_number,
                    awaiting_intent_confirmation=True,
                    pending_intent_message=text,
                    pending_intent=intent_result.intent
                )
                
                # Generate a helpful clarification question directly
                # Check if it's car-related to provide better context
                try:
                    is_car_related = await is_car_related_llm(text, intent_result)
                    car_context = "I see you're asking about something car-related" if is_car_related else "I'm not entirely sure what you're looking for"
                except Exception as e:
                    print(f"Error checking car-related: {e}")
                    car_context = "I want to make sure I understand correctly"
                
                clarification_message = (
                    f"🤔 {car_context}.\n\n"
                    f"Could you please clarify what you'd like to do?\n\n"
                    f"For example:\n"
                    f"• Browse used cars\n"
                    f"• Get car valuation\n"
                    f"• Calculate EMI\n"
                    f"• Book a service\n\n"
                    f"Just let me know what you need! 😊"
                )
                
                await send_whatsapp_message(from_number, clarification_message, user_message=text)
                print(f"Sent intent clarification request to {from_number}")
                return
        
        # Step 3: Use LLM-based router to determine flow routing
        routing_result = None
        target_flow = None
        try:
            routing_result = await route_to_flow(
                text,
                conversation_context=conversation_context if conversation_context else None,
                current_flow=current_flow,
                current_step=current_step,
                intent_result=intent_result
            )
            print("Flow routing result:")
            print(f"  Target flow: {routing_result.target_flow}")
            print(f"  Confidence: {routing_result.confidence:.2f}")
            print(f"  Should switch: {routing_result.should_switch}")
            print(f"  Reasoning: {routing_result.reasoning}")
            
            target_flow = routing_result.target_flow if routing_result.should_switch else None
            
        except FlowRoutingError as routing_exc:
            print(f"Flow routing failed: {routing_exc}, falling back to keyword-based detection")
            # Fallback to keyword-based detection if LLM routing fails
            target_flow = detect_flow_switch(intent_result, text, current_flow)
            routing_result = None  # Set to None to indicate fallback was used
        
        # Step 4: Handle flow switching or continue current flow
        # If user wants to switch to a different flow, clear current state and route to new flow
        if target_flow and target_flow != current_flow:
            print(f"Flow switch detected: {current_flow} -> {target_flow}")
            conversation_manager.clear_state(from_number)
            
            # Route to the new flow immediately
            if target_flow == "service_booking":
                try:
                    from service_booking_flow import handle_service_booking_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_service_booking_flow, from_number, text, intent_result
                    )
                    # Check if the new flow also requested a switch (shouldn't happen, but safety check)
                    switch_response = await handle_flow_switch_marker(
                        response_text, from_number, text, intent_result, "service_booking"
                    )
                    if switch_response is not None:
                        response_text = switch_response
                        # Prevent further nesting
                        if response_text and response_text.startswith("__FLOW_SWITCH__:"):
                            print(f"Warning: Nested flow switch detected, sending fallback message")
                            response_text = "I'm having trouble switching flows. Please try again with a clear request."
                    await send_whatsapp_message(from_number, response_text, user_message=text)
                    print(f"Switched to service booking flow for {from_number}")
                    return
                except Exception as flow_exc:
                    print(f"Error switching to service booking flow: {flow_exc}")
            
            elif target_flow == "emi":
                try:
                    from emi_flow import handle_emi_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_emi_flow, from_number, text, intent_result
                    )
                    # Check if the new flow also requested a switch (shouldn't happen, but safety check)
                    switch_response = await handle_flow_switch_marker(
                        response_text, from_number, text, intent_result, "emi"
                    )
                    if switch_response is not None:
                        response_text = switch_response
                        # Prevent further nesting
                        if response_text and response_text.startswith("__FLOW_SWITCH__:"):
                            print(f"Warning: Nested flow switch detected, sending fallback message")
                            response_text = "I'm having trouble switching flows. Please try again with a clear request."
                    await send_whatsapp_message(from_number, response_text, user_message=text)
                    print(f"Switched to EMI flow for {from_number}")
                    return
                except Exception as flow_exc:
                    print(f"Error switching to EMI flow: {flow_exc}")
            
            elif target_flow == "car_valuation":
                try:
                    from car_valuation_flow import handle_car_valuation_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_car_valuation_flow, from_number, text, intent_result
                    )
                    # Check if the new flow also requested a switch (shouldn't happen, but safety check)
                    switch_response = await handle_flow_switch_marker(
                        response_text, from_number, text, intent_result, "car_valuation"
                    )
                    if switch_response is not None:
                        response_text = switch_response
                        # Prevent further nesting
                        if response_text and response_text.startswith("__FLOW_SWITCH__:"):
                            print(f"Warning: Nested flow switch detected, sending fallback message")
                            response_text = "I'm having trouble switching flows. Please try again with a clear request."
                    await send_whatsapp_message(from_number, response_text, user_message=text)
                    print(f"Switched to car valuation flow for {from_number}")
                    return
                except Exception as flow_exc:
                    print(f"Error switching to car valuation flow: {flow_exc}")
            
            elif target_flow == "browse_car":
                try:
                    response_text = await call_flow_handler_with_timeout(
                        handle_browse_car_flow, from_number, text, intent_result
                    )
                    # Check if the new flow also requested a switch (shouldn't happen, but safety check)
                    switch_response = await handle_flow_switch_marker(
                        response_text, from_number, text, intent_result, "browse_car"
                    )
                    if switch_response is not None:
                        response_text = switch_response
                        # Prevent further nesting
                        if response_text and response_text.startswith("__FLOW_SWITCH__:"):
                            print(f"Warning: Nested flow switch detected, sending fallback message")
                            response_text = "I'm having trouble switching flows. Please try again with a clear request."
                    await send_whatsapp_message(from_number, response_text, user_message=text)
                    print(f"Switched to browse car flow for {from_number}")
                    return
                except Exception as flow_exc:
                    print(f"Error switching to browse car flow: {flow_exc}")
        
        # Step 5: Route to appropriate flow based on current state (no switch detected)
        # Get state again in case it was updated
        state = conversation_manager.get_state(from_number)
        
        if state and state.flow_name == "browse_car":
            # User is in browse car flow, handle it directly
            try:
                response_text = await call_flow_handler_with_timeout(
                    handle_browse_car_flow, from_number, text, intent_result
                )
                
                # Check if flow requested a switch
                switch_response = await handle_flow_switch_marker(
                    response_text, from_number, text, intent_result, "browse_car"
                )
                if switch_response is not None:
                    response_text = switch_response
                    # Check if the new flow also requested a switch (prevent infinite loops)
                    if response_text and response_text.startswith("__FLOW_SWITCH__:"):
                        print(f"Warning: Nested flow switch detected, sending fallback message")
                        response_text = "I'm having trouble switching flows. Please try again with a clear request."
                
                await send_whatsapp_message(from_number, response_text, user_message=text)
                print(f"Browse car flow response sent to {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error in browse car flow: {flow_exc}")
                # Fall through to normal processing
        
        elif state and state.flow_name == "car_valuation":
            # User is in car valuation flow, handle it directly
            try:
                from car_valuation_flow import handle_car_valuation_flow
                response_text = await call_flow_handler_with_timeout(
                    handle_car_valuation_flow, from_number, text, intent_result
                )
                
                # Check if flow requested a switch
                switch_response = await handle_flow_switch_marker(
                    response_text, from_number, text, intent_result, "car_valuation"
                )
                if switch_response is not None:
                    response_text = switch_response
                    # Check if the new flow also requested a switch (prevent infinite loops)
                    if response_text and response_text.startswith("__FLOW_SWITCH__:"):
                        print(f"Warning: Nested flow switch detected, sending fallback message")
                        response_text = "I'm having trouble switching flows. Please try again with a clear request."
                
                await send_whatsapp_message(from_number, response_text, user_message=text)
                print(f"Car valuation flow response sent to {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error in car valuation flow: {flow_exc}")
                # Fall through to normal processing
        
        elif state and state.flow_name == "emi":
            # User is in EMI flow, handle it directly
            try:
                from emi_flow import handle_emi_flow
                response_text = await call_flow_handler_with_timeout(
                    handle_emi_flow, from_number, text, intent_result
                )
                
                # Check if flow requested a switch
                switch_response = await handle_flow_switch_marker(
                    response_text, from_number, text, intent_result, "emi"
                )
                if switch_response is not None:
                    response_text = switch_response
                    # Check if the new flow also requested a switch (prevent infinite loops)
                    if response_text and response_text.startswith("__FLOW_SWITCH__:"):
                        print(f"Warning: Nested flow switch detected, sending fallback message")
                        response_text = "I'm having trouble switching flows. Please try again with a clear request."
                
                await send_whatsapp_message(from_number, response_text, user_message=text)
                print(f"EMI flow response sent to {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error in EMI flow: {flow_exc}")
                # Fall through to normal processing
        
        elif state and state.flow_name == "service_booking":
            # User is in service booking flow, handle it directly
            try:
                from service_booking_flow import handle_service_booking_flow
                response_text = await call_flow_handler_with_timeout(
                    handle_service_booking_flow, from_number, text, intent_result
                )
                
                # Check if flow requested a switch
                switch_response = await handle_flow_switch_marker(
                    response_text, from_number, text, intent_result, "service_booking"
                )
                if switch_response is not None:
                    response_text = switch_response
                    # Check if the new flow also requested a switch (prevent infinite loops)
                    if response_text and response_text.startswith("__FLOW_SWITCH__:"):
                        print(f"Warning: Nested flow switch detected, sending fallback message")
                        response_text = "I'm having trouble switching flows. Please try again with a clear request."
                
                await send_whatsapp_message(from_number, response_text, user_message=text)
                print(f"Service booking flow response sent to {from_number}")
                return
            except Exception as flow_exc:
                print(f"Error in service booking flow: {flow_exc}")
                # Fall through to normal processing
        
        # Step 6: If no active flow, route to detected flow using LLM router
        # Check if routing result suggests a flow (when not in active flow)
        if not current_flow and routing_result and routing_result.target_flow:
            target_flow = routing_result.target_flow
            
            if target_flow == "service_booking":
                try:
                    from service_booking_flow import handle_service_booking_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_service_booking_flow, from_number, text, intent_result
                    )
                    await send_whatsapp_message(from_number, response_text, user_message=text)
                    print(f"Service booking flow initiated for {from_number}")
                    return
                except Exception as flow_exc:
                    print(f"Error initiating service booking flow: {flow_exc}")
                    # Fall through to normal processing
            
            elif target_flow == "emi":
                try:
                    from emi_flow import handle_emi_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_emi_flow, from_number, text, intent_result
                    )
                    await send_whatsapp_message(from_number, response_text, user_message=text)
                    print(f"EMI flow initiated for {from_number}")
                    return
                except Exception as flow_exc:
                    print(f"Error initiating EMI flow: {flow_exc}")
                    # Fall through to normal processing
            
            elif target_flow == "car_valuation":
                try:
                    from car_valuation_flow import handle_car_valuation_flow
                    response_text = await call_flow_handler_with_timeout(
                        handle_car_valuation_flow, from_number, text, intent_result
                    )
                    await send_whatsapp_message(from_number, response_text, user_message=text)
                    print(f"Car valuation flow initiated for {from_number}")
                    return
                except Exception as flow_exc:
                    print(f"Error initiating car valuation flow: {flow_exc}")
                    # Fall through to normal processing
            
            elif target_flow == "browse_car":
                try:
                    response_text = await call_flow_handler_with_timeout(
                        handle_browse_car_flow, from_number, text, intent_result
                    )
                    await send_whatsapp_message(from_number, response_text, user_message=text)
                    print(f"Browse car flow initiated for {from_number}")
                    return
                except Exception as flow_exc:
                    print(f"Error initiating browse car flow: {flow_exc}")
                    # Fall through to normal processing
        
        # Step 7: Determine if the query is car-related using LLM for better accuracy
        try:
            car_related = await is_car_related_llm(text, intent_result)
            print(f"  Car-related: {car_related}")
        except Exception as car_check_exc:
            print(f"LLM car-related check failed: {car_check_exc}, using keyword-based fallback")
            car_related = is_car_related(intent_result, text)
            print(f"  Car-related (fallback): {car_related}")
        
        # Step 8: Generate human-like response based on intent
        try:
            response_text = await generate_response(
                original_message=text,
                intent_result=intent_result,
                is_car_related=car_related
            )
            print(f"Generated response: {response_text}")
            
            # Step 9: Send the response back to the user
            await send_whatsapp_message(from_number, response_text, user_message=text)
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
            await send_whatsapp_message(from_number, fallback, user_message=text)
            print(f"Fallback response sent to {from_number}")
            
    except IntentExtractionError as exc:
        print(f"Intent extraction failed: {exc}")
        # Fallback for intent extraction failures
        fallback = (
            "I'm having some technical difficulties understanding your message. "
            "Could you please rephrase your question about cars? I'm here to help!"
        )
        await send_whatsapp_message(from_number, fallback, user_message=text)
        
    except ValueError as exc:
        print(f"Invalid message for intent extraction: {exc}")
        # Handle empty or invalid messages
        fallback = (
            "I didn't quite catch that. Could you please send me a message "
            "about your car? I'm here to help with car-related questions!"
        )
        await send_whatsapp_message(from_number, fallback, user_message=text)
    
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
            await send_whatsapp_message(from_number, fallback, user_message=text)
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
    access_token: Optional[str] = None,
    user_message: Optional[str] = None
):
    """
    Send a WhatsApp message using Meta's API and track conversation history.
    This is a helper function - you'll need to implement the actual API call
    
    Args:
        to: Recipient phone number
        message: Message text (will be validated and sanitized)
        phone_number_id: Optional phone number ID override
        access_token: Optional access token override
        user_message: Optional user message to track in conversation history
    """
    import httpx
    
    # Validate and sanitize message before sending
    validated_message = validate_and_sanitize_response(message)
    print(f"📤 SENDING MESSAGE TO {to}: {validated_message[:200]}{'...' if len(validated_message) > 200 else ''}")
    
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
            "body": validated_message
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            print(f"Message sent successfully: {response.json()}")
            
            # Track conversation history if user message is provided
            if user_message:
                conversation_manager.add_message_to_history(to, user_message, validated_message)
            
            return response.json()
    except httpx.HTTPError as e:
        print(f"Error sending message: {e}")
        raise


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

