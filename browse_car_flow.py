"""Browse Used Car Flow Handler."""

import re
from typing import Optional, List, Dict, Any
from conversation_state import conversation_manager, ConversationState
from database import car_db, Car
from intent_service import generate_response
from browse_car_analyzer import (
    analyze_browse_car_message,
    generate_browse_car_response,
    BrowseCarAnalysisError,
)
from route import llm_route

# Cache for brands and car types (fetched from database)
_brands_cache: Optional[List[str]] = None
_car_types_cache: Optional[List[str]] = None


async def get_brands_from_db() -> List[str]:
    """Get available brands from database."""
    global _brands_cache
    if _brands_cache is None and car_db:
        try:
            _brands_cache = await car_db.get_available_brands()
        except Exception as e:
            print(f"Error fetching brands from database: {e}")
            _brands_cache = []
    return _brands_cache or []


async def get_car_types_from_db() -> List[str]:
    """Get available car types from database."""
    global _car_types_cache
    if _car_types_cache is None and car_db:
        try:
            _car_types_cache = await car_db.get_available_car_types()
        except Exception as e:
            print(f"Error fetching car types from database: {e}")
            _car_types_cache = []
    return _car_types_cache or []


def clear_brands_cache():
    """Clear brands cache to force refresh from database."""
    global _brands_cache
    _brands_cache = None


def clear_car_types_cache():
    """Clear car types cache to force refresh from database."""
    global _car_types_cache
    _car_types_cache = None


async def extract_brand_from_message(message: str) -> Optional[str]:
    """Extract car brand from user message by checking against database brands."""
    message_lower = message.lower()
    brands = await get_brands_from_db()
    
    # Check for exact or partial matches
    for brand in brands:
        brand_lower = brand.lower()
        if brand_lower in message_lower or message_lower in brand_lower:
            return brand  # Return as stored in database
    
    return None


def extract_budget_from_message(message: str) -> Optional[tuple]:
    """Extract budget range from message. Returns (min, max) in lakhs."""
    message_lower = message.lower()
    
    # Look for patterns like "5 lakh", "5-10 lakh", "under 10 lakh"
    patterns = [
        r'(\d+)\s*-\s*(\d+)\s*lakh',
        r'(\d+)\s*to\s*(\d+)\s*lakh',
        r'between\s*(\d+)\s*and\s*(\d+)\s*lakh',
        r'under\s*(\d+)\s*lakh',
        r'upto\s*(\d+)\s*lakh',
        r'(\d+)\s*lakh',
        r'(\d+)\s*lac',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if match:
            if len(match.groups()) == 2:
                min_price = float(match.group(1)) * 100000  # Convert to rupees
                max_price = float(match.group(2)) * 100000
                return (min_price, max_price)
            elif len(match.groups()) == 1:
                max_price = float(match.group(1)) * 100000
                return (None, max_price)
    
    return None


async def extract_car_type_from_message(message: str) -> Optional[str]:
    """Extract car type from user message by checking against database car types."""
    message_lower = message.lower()
    car_types = await get_car_types_from_db()
    
    # Check for exact or partial matches
    for car_type in car_types:
        car_type_lower = car_type.lower()
        if car_type_lower in message_lower or message_lower in car_type_lower:
            return car_type  # Return as stored in database
    
    return None


def format_car_list(cars: List[Car]) -> str:
    """Format list of cars for display."""
    if not cars:
        return "Sorry, I couldn't find any cars matching your criteria. Would you like to adjust your search?"
    
    message = f"Great! I found {len(cars)} car(s) for you:\n\n"
    
    for idx, car in enumerate(cars, start=1):
        price_lakhs = (car.price or 0) / 100000
        year_str = f"({car.year})" if car.year else ""
        variant_str = f" {car.variant}" if car.variant else ""
        
        message += f"*{idx}. {car.brand or 'N/A'} {car.model or 'N/A'}{variant_str} {year_str}*\n"
        message += f"   💰 Price: ₹{price_lakhs:.2f} Lakh\n"
        if car.type:
            message += f"   🚗 Type: {car.type}\n"
        if car.fuel_type:
            message += f"   ⛽ Fuel: {car.fuel_type}\n"
        if car.transmission:
            message += f"   🔧 Transmission: {car.transmission}\n"
        if car.mileage:
            message += f"   📊 Mileage: {car.mileage:,} km\n"
        if car.registration_number:
            message += f"   🆔 Reg: {car.registration_number}\n"
        message += "\n"
    
    message += "Please reply with the *number* of the car you're interested in, or type 'change' to modify your search criteria."
    
    return message


    async def handle_browse_car_flow(user_id: str, message: str, intent_result: Any) -> str:
        """
        MAIN FLOW HANDLER FOR BROWSE USED CARS (WITH MEMORY FIX)
        """
        state = conversation_manager.get_state(user_id)
        message_lower = message.lower().strip()

        # --- Step 1: pending flow switch confirmation ---
        if state and state.data.get("pending_flow"):
            pending = state.data["pending_flow"]

            if message_lower in ["yes", "y", "ok", "sure"]:
                conversation_manager.clear_state(user_id)
                conversation_manager.set_state(
                    user_id,
                    ConversationState(
                        user_id=user_id,
                        flow_name=pending,
                        step="start",
                        data={}
                    )
                )

                # redirect to selected flow
                if pending == "car_valuation":
                    return await handle_car_valuation_flow(user_id, message, None)
                elif pending == "service":
                    return await handle_service_flow(user_id, message, None)
                elif pending == "emi":
                    return await handle_emi_flow(user_id, message, None)
                else:
                    return f"Switched to '{pending}'. Let's begin!"

            # user cancelled flow switch → stay here
            conversation_manager.update_data(user_id, pending_flow=None)
            return "👍 No problem! Let's continue with browsing cars."

        # --- Step 2: LLM flow routing (only if NOT inside browse_car) ---
        if not state or state.flow_name != "browse_car":
            route = await llm_route(message)
            new_flow = route["intent"]
            confidence = route["confidence"]

            FLOW_MAP = {
                "browse_used_cars": "browse_car",
                "car_validation": "car_valuation",
                "emi_options": "emi",
                "service_booking": "service",
                "normal": "normal"
            }
            mapped_flow = FLOW_MAP.get(new_flow, "normal")

            # user tries switching from outside or before starting
            if mapped_flow != "browse_car" and mapped_flow != "normal":
                conversation_manager.set_state(
                    user_id,
                    ConversationState(
                        user_id=user_id,
                        flow_name="browse_car",
                        step="collecting_criteria",
                        data={"pending_flow": mapped_flow}
                    )
                )
                return (
                    f"It seems you want to switch to **{mapped_flow.replace('_',' ')}**.\n"
                    "Do you want to leave the Browse Cars flow? (Yes/No)"
                )

        # --- Step 3: Exit keywords ---
        exit_keywords = ["back", "menu", "exit", "cancel", "quit", "stop", "main menu", "done"]
        if any(k in message_lower for k in exit_keywords):
            conversation_manager.clear_state(user_id)
            return (
                "Sure! How can I help you today? 😊\n\n"
                "• Browse used cars\n"
                "• Get car valuation\n"
                "• Calculate EMI\n"
                "• Book a service\n"
            )

        # --- Step 4: Initialize flow if needed ---
        if not state or state.flow_name != "browse_car":
            state = ConversationState(
                user_id=user_id,
                flow_name="browse_car",
                step="collecting_criteria",
                data={}
            )
            conversation_manager.set_state(user_id, state)

        # -- STEP 5: LLM message analysis w/ MEMORY MERGE --
        available_brands = await get_brands_from_db()
        available_types = await get_car_types_from_db()

        analysis = await analyze_browse_car_message(
            message=message,
            conversation_context={"step": state.step, "data": state.data},
            available_brands=available_brands,
            available_types=available_types
        )

        # extracted values
        brand = analysis.get("extracted_brand")
        budget_max = analysis.get("extracted_budget_max")
        budget_min = analysis.get("extracted_budget_min")
        car_type = analysis.get("extracted_type")

        # FIX: MEMORY MERGING — ONLY UPDATE WHAT USER CHANGES
        new_data = {
            "brand": brand or state.data.get("brand"),
            "budget_min": budget_min or state.data.get("budget_min"),
            "budget_max": budget_max or state.data.get("budget_max"),
            "car_type": car_type or state.data.get("car_type")
        }

        # save merged memory
        conversation_manager.update_data(user_id, **new_data)

        # If clarification needed → respond immediately
        if analysis.get("needs_clarification"):
            return analysis["clarification_question"]

        # --- Step 6: Continue flow based on step ---
        state = conversation_manager.get_state(user_id)

        if state.step == "collecting_criteria":
            return await handle_collecting_criteria(user_id, message, state)

        elif state.step == "showing_cars":
            return await handle_showing_cars(user_id, message, state)

        elif state.step == "car_selected":
            return await handle_car_selected(user_id, message, state)

        elif state.step.startswith("test_drive_"):
            return await handle_test_drive_steps(user_id, message, state)

        # fallback
        return "Got it! How can I help you with browsing cars?"

async def handle_collecting_criteria(user_id: str, message: str, state: ConversationState):
    """
    Step 1 — Collect brand, budget, car type.
    Once enough info is present → move to showing_cars
    """
    data = state.data

    brand = data.get("brand")
    budget_min = data.get("budget_min")
    budget_max = data.get("budget_max")
    car_type = data.get("car_type")

    # If still incomplete → ask for next missing detail
    if not brand:
        return "Got it! Which car brand are you interested in?"
    if not budget_min and not budget_max:
        return "Great! What is your budget range?"
    if not car_type:
        return "Nice! What type of car do you prefer? (SUV, Sedan, Hatchback)"

    # If everything is present → go to next step
    conversation_manager.update_state(
        user_id,
        flow_name="browse_car",
        step="showing_cars"
    )

    return await handle_showing_cars(user_id, message, conversation_manager.get_state(user_id))



async def handle_showing_cars(user_id: str, message: str, state: ConversationState):
    """
    Step 2 — Show matching cars from DB.
    """
    data = state.data

    brand = data.get("brand")
    budget_min = data.get("budget_min")
    budget_max = data.get("budget_max")
    car_type = data.get("car_type")

    # Fetch cars from DB
    cars = await fetch_cars_from_db(
        brand=brand,
        min_price=budget_min,
        max_price=budget_max,
        car_type=car_type
    )

    if not cars:
        return (
            f"Sorry, I couldn't find any {brand} cars under your criteria.\n"
            "Would you like to try another brand or change your budget?"
        )

    # Store list so user can select
    conversation_manager.update_data(user_id, available_cars=cars)

    text = "Here are the best matches:\n\n"
    for idx, car in enumerate(cars, start=1):
        text += f"{idx}. {car['brand']} {car['model']} - ₹{car['price']}\n"

    text += "\nPlease enter the number of the car you want to see details for."

    return text



async def handle_car_selected(user_id: str, message: str, state: ConversationState):
    """
    Step 3 — User selects a car (number)
    """
    try:
        choice = int(message.strip())
    except:
        return "Please enter a valid number from the list above."

    cars = state.data.get("available_cars", [])

    if not 1 <= choice <= len(cars):
        return "Invalid choice. Please enter a valid number."

    car = cars[choice - 1]

    # Save selected car
    conversation_manager.update_data(user_id, selected_car=car)

    conversation_manager.update_state(
        user_id,
        flow_name="browse_car",
        step="test_drive_start"
    )

    return (
        f"Great choice! Here are the details:\n\n"
        f"Brand: {car['brand']}\n"
        f"Model: {car['model']}\n"
        f"Year: {car['year']}\n"
        f"Price: ₹{car['price']}\n\n"
        "Would you like to book a test drive? (Yes/No)"
    )



async def handle_test_drive_steps(user_id: str, message: str, state: ConversationState):
    """
    Step 4 — Test-drive booking flow
    """
    message = message.lower().strip()

    # Step: test_drive_start
    if state.step == "test_drive_start":
        if message in ["yes", "y", "sure"]:
            conversation_manager.update_state(
                user_id, flow_name="browse_car", step="test_drive_name"
            )
            return "Great! Please share your full name for the booking."
        else:
            return "Alright! Let me know if you'd like help with anything else."

    # Step: test_drive_name
    if state.step == "test_drive_name":
        conversation_manager.update_data(user_id, user_name=message)
        conversation_manager.update_state(
            user_id, flow_name="browse_car", step="test_drive_phone"
        )
        return "Thanks! Please provide your phone number."

    # Step: test_drive_phone
    if state.step == "test_drive_phone":
        conversation_manager.update_data(user_id, phone=message)
        conversation_manager.update_state(
            user_id, flow_name="browse_car", step="test_drive_booking"
        )
        return "Perfect! What date would you like to book the test drive?"

    # Step: test_drive_booking
    if state.step == "test_drive_booking":
        booking_date = message
        saved = state.data

        await save_test_drive_booking(
            car=saved["selected_car"],
            name=saved["user_name"],
            phone=saved["phone"],
            date=booking_date
        )

        conversation_manager.clear_state(user_id)

        return (
            "🎉 Your test drive has been booked successfully!\n\n"
            f"Car: {saved['selected_car']['brand']} {saved['selected_car']['model']}\n"
            f"Date: {booking_date}\n"
            f"Name: {saved['user_name']}\n"
            f"Phone: {saved['phone']}\n\n"
            "Let me know if you want to explore more cars!"
        )


async def handle_browse_car_flow(user_id: str, message: str, intent_result: Any = None,state: ConversationState | None = None) -> str:
    """
    BROWSE USED CAR FLOW — FULLY FIXED VERSION
    Handles memory stability, LLM routing, merging, and step navigation
    """
    state = conversation_manager.get_state(user_id)
    message_lower = message.lower().strip()

    # -----------------------------------------------------------
    # 1) Handle pending flow switch (Yes/No confirmation)
    # -----------------------------------------------------------
    if state and state.data.get("pending_flow"):
        pending = state.data["pending_flow"]

        if message_lower in ["yes", "y", "ok", "sure"]:
            conversation_manager.clear_state(user_id)
            conversation_manager.set_state(
                user_id,
                ConversationState(user_id, pending, "start", {})
            )
            if pending == "car_valuation":
                return await handle_car_valuation_flow(user_id, message, None)
            if pending == "service":
                return await handle_service_flow(user_id, message, None)
            if pending == "emi":
                return await handle_emi_flow(user_id, message, None)
            return f"Switched to {pending}. Let's begin!"

        # user said "no"
        conversation_manager.update_data(user_id, pending_flow=None)
        return "👍 No problem! Let's continue browsing cars."

    # -----------------------------------------------------------
    # 2) Check if user wants another flow (Router)
    # -----------------------------------------------------------
    if not state or state.flow_name != "browse_car":
        route = await llm_route(message)
        new_flow = route["intent"]

        FLOW_MAP = {
            "browse_used_cars": "browse_car",
            "car_validation": "car_valuation",
            "emi_options": "emi",
            "service_booking": "service",
            "normal": "normal",
        }

        mapped_flow = FLOW_MAP.get(new_flow, "normal")

        # ask before switching to another flow
        if mapped_flow != "browse_car" and mapped_flow != "normal":
            conversation_manager.set_state(
                user_id,
                ConversationState(
                    user_id,
                    "browse_car",
                    "collecting_criteria",
                    {"pending_flow": mapped_flow}
                )
            )
            return (
                f"It seems you want to switch to *{mapped_flow.replace('_',' ')}*.\n"
                "Do you want to leave browsing cars? (Yes/No)"
            )

    # -----------------------------------------------------------
    # 3) EXIT the flow
    # -----------------------------------------------------------
    exit_keywords = ["back", "menu", "exit", "cancel", "quit", "stop", "done"]
    if any(k in message_lower for k in exit_keywords):
        conversation_manager.clear_state(user_id)
        return (
            "Sure! How can I help you today? 😊\n\n"
            "• Browse used cars\n"
            "• Get car valuation\n"
            "• Calculate EMI\n"
            "• Book a service\n"
        )

    # -----------------------------------------------------------
    # 4) Initialize browse_car flow (FIRST TIME ONLY)
    # -----------------------------------------------------------
    if not state:
        state = ConversationState(
            user_id=user_id,
            flow_name="browse_car",
            step="collecting_criteria",
            data={}
        )
        conversation_manager.set_state(user_id, state)

    elif state.flow_name != "browse_car":
        # switching INTO browse_car without losing memory
        state = ConversationState(
            user_id=user_id,
            flow_name="browse_car",
            step="collecting_criteria",
            data=state.data  # keep memory!
        )
        conversation_manager.set_state(user_id, state)

    # reload after possible change
    state = conversation_manager.get_state(user_id)

    # -----------------------------------------------------------
    # 5) LLM Analysis (with REAL MEMORY PASSED)
    # -----------------------------------------------------------
    available_brands = await get_brands_from_db()
    available_types = await get_car_types_from_db()

    analysis = await analyze_browse_car_message(
        message=message,
        conversation_context={"step": state.step, "data": state.data},
        available_brands=available_brands,
        available_types=available_types,
    )

    # extract values from analysis
    brand = analysis.get("extracted_brand")
    car_type = analysis.get("extracted_type")
    budget_min = analysis.get("extracted_budget_min")
    budget_max = analysis.get("extracted_budget_max")

    # -----------------------------------------------------------
    # 6) PERFECT MEMORY MERGE (NEVER overwrite with None)
    # -----------------------------------------------------------
    merged = {
        "brand": brand if brand is not None else state.data.get("brand"),
        "car_type": car_type if car_type is not None else state.data.get("car_type"),
        "budget_min": budget_min if budget_min is not None else state.data.get("budget_min"),
        "budget_max": budget_max if budget_max is not None else state.data.get("budget_max"),
        "last_intent": analysis.get("user_intent"),
    }

    conversation_manager.update_data(user_id, **merged)

    # -----------------------------------------------------------
    # 7) Clarification → immediate response
    # -----------------------------------------------------------
    if analysis.get("needs_clarification"):
        return analysis["clarification_question"]

    # -----------------------------------------------------------
    # 8) Continue flow based on step
    # -----------------------------------------------------------
    updated = conversation_manager.get_state(user_id)

    if updated.step == "collecting_criteria":
        return await handle_collecting_criteria(user_id, message, updated)

    if updated.step == "showing_cars":
        return await handle_showing_cars(user_id, message, updated)

    if updated.step == "car_selected":
        return await handle_car_selected(user_id, message, updated)

    if updated.step.startswith("test_drive_"):
        return await handle_test_drive_steps(user_id, message, updated)

    # fallback
    return "Got it! How can I help you with browsing cars?"
