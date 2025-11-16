"""EMI (Equated Monthly Installment) Flow Handler."""

import re
import math
from typing import Optional, List, Dict, Any
from conversation_state import conversation_manager, ConversationState
from database import car_db, Car
from intent_service import generate_response
from emi_analyzer import (
    analyze_emi_message,
    generate_emi_response,
    EMIAnalysisError,
)

# Standard interest rates (annual) - can be configured
DEFAULT_INTEREST_RATE = 9.5  # 9.5% per annum
EMI_TENURE_OPTIONS = [12, 24, 36, 48, 60, 72]  # months


async def get_brands_from_db() -> List[str]:
    """Get available brands from database."""
    if car_db:
        try:
            return await car_db.get_available_brands()
        except Exception as e:
            print(f"Error fetching brands from database: {e}")
            return []
    return []


def extract_down_payment_from_message(message: str) -> Optional[float]:
    """Extract down payment amount from message. Returns amount in rupees."""
    message_lower = message.lower()
    
    # Look for patterns like "5 lakh", "500000", "5-10 lakh", "under 5 lakh"
    patterns = [
        r'(\d+)\s*lakh',
        r'(\d+)\s*lac',
        r'₹?\s*(\d{1,2}[,\d]*)\s*lakh',
        r'₹?\s*(\d{4,})',  # Direct rupee amount (4+ digits)
        r'(\d+)\s*thousand',
        r'(\d+)\s*k',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if match:
            amount = match.group(1).replace(',', '')
            try:
                amount_float = float(amount)
                # If it's a small number (< 100), assume it's in lakhs
                if amount_float < 100:
                    return amount_float * 100000  # Convert lakhs to rupees
                elif amount_float < 10000:
                    # Could be in thousands or lakhs - check context
                    if 'lakh' in message_lower or 'lac' in message_lower:
                        return amount_float * 100000
                    else:
                        return amount_float * 1000
                else:
                    return amount_float
            except ValueError:
                continue
    
    return None


def calculate_emi(principal: float, annual_rate: float, tenure_months: int) -> Dict[str, Any]:
    """Calculate EMI using the standard formula.
    
    Formula: EMI = [P × R × (1+R)^N] / [(1+R)^N - 1]
    Where:
    P = Principal amount (loan amount)
    R = Monthly interest rate (annual_rate / 12 / 100)
    N = Number of months
    
    Returns:
        {
            "emi": float,
            "total_amount": float,
            "total_interest": float,
            "principal": float,
            "rate": float,
            "tenure_months": int
        }
    """
    if principal <= 0 or tenure_months <= 0:
        return {
            "emi": 0,
            "total_amount": 0,
            "total_interest": 0,
            "principal": principal,
            "rate": annual_rate,
            "tenure_months": tenure_months
        }
    
    monthly_rate = annual_rate / 12 / 100  # Convert annual % to monthly decimal
    
    if monthly_rate == 0:
        # No interest - simple division
        emi = principal / tenure_months
    else:
        # Standard EMI formula
        emi = (principal * monthly_rate * (1 + monthly_rate) ** tenure_months) / \
              ((1 + monthly_rate) ** tenure_months - 1)
    
    total_amount = emi * tenure_months
    total_interest = total_amount - principal
    
    return {
        "emi": round(emi, 2),
        "total_amount": round(total_amount, 2),
        "total_interest": round(total_interest, 2),
        "principal": principal,
        "rate": annual_rate,
        "tenure_months": tenure_months
    }


def format_emi_options(car: Dict[str, Any], down_payment: float, interest_rate: float = DEFAULT_INTEREST_RATE) -> str:
    """Format EMI options for different tenures."""
    car_price = car.get("price", 0)
    if car_price <= 0:
        return "I couldn't find the car price. Please select a valid car."
    
    loan_amount = car_price - down_payment
    
    if loan_amount <= 0:
        return (
            f"Your down payment of ₹{down_payment:,.0f} is equal to or more than the car price of ₹{car_price:,.0f}. "
            f"No loan is needed! 🎉"
        )
    
    message = (
        f"📊 *EMI Options for {car.get('brand', 'N/A')} {car.get('model', 'N/A')}*\n\n"
        f"*Car Price:* ₹{car_price:,.0f}\n"
        f"*Down Payment:* ₹{down_payment:,.0f}\n"
        f"*Loan Amount:* ₹{loan_amount:,.0f}\n"
        f"*Interest Rate:* {interest_rate}% per annum\n\n"
        f"*EMI Options:*\n\n"
    )
    
    for tenure in EMI_TENURE_OPTIONS:
        emi_data = calculate_emi(loan_amount, interest_rate, tenure)
        emi = emi_data["emi"]
        total_interest = emi_data["total_interest"]
        
        years = tenure // 12
        months = tenure % 12
        tenure_display = f"{years} years" if months == 0 else f"{years} years {months} months" if years > 0 else f"{months} months"
        
        message += f"*{tenure} months* ({tenure_display}):\n"
        message += f"   💰 Monthly EMI: ₹{emi:,.0f}\n"
        message += f"   📈 Total Interest: ₹{total_interest:,.0f}\n"
        message += f"   💵 Total Amount: ₹{emi_data['total_amount']:,.0f}\n\n"
    
    message += "Please select a tenure option (12, 24, 36, 48, 60, or 72 months) to proceed."
    
    return message


def format_emi_result(car: Dict[str, Any], down_payment: float, tenure: int, emi_data: Dict[str, Any], interest_rate: float = DEFAULT_INTEREST_RATE) -> str:
    """Format final EMI calculation result."""
    car_price = car.get("price", 0)
    loan_amount = emi_data["principal"]
    emi = emi_data["emi"]
    total_amount = emi_data["total_amount"]
    total_interest = emi_data["total_interest"]
    
    years = tenure // 12
    months = tenure % 12
    tenure_display = f"{years} years" if months == 0 else f"{years} years {months} months" if years > 0 else f"{months} months"
    
    message = (
        f"💰 *EMI Calculation Result*\n\n"
        f"*Car Details:*\n"
        f"• {car.get('brand', 'N/A')} {car.get('model', 'N/A')}\n"
        f"• Price: ₹{car_price:,.0f}\n\n"
        f"*Loan Details:*\n"
        f"• Down Payment: ₹{down_payment:,.0f}\n"
        f"• Loan Amount: ₹{loan_amount:,.0f}\n"
        f"• Interest Rate: {interest_rate}% per annum\n"
        f"• Tenure: {tenure} months ({tenure_display})\n\n"
        f"*Monthly EMI:*\n"
        f"💵 ₹{emi:,.0f} per month\n\n"
        f"*Breakdown:*\n"
        f"• Total Amount Payable: ₹{total_amount:,.0f}\n"
        f"• Total Interest: ₹{total_interest:,.0f}\n\n"
        f"*Note:* This is an approximate calculation. Final EMI may vary based on your credit profile and bank policies.\n\n"
        f"Would you like to:\n"
        f"1️⃣ Calculate EMI for another car\n"
        f"2️⃣ Change down payment or tenure\n"
        f"3️⃣ Get more information"
    )
    
    return message


async def handle_emi_flow(
    user_id: str,
    message: str,
    intent_result: Any
) -> str:
    """Handle the EMI calculation flow with intelligent message analysis."""
    state = conversation_manager.get_state(user_id)
    
    # Get available brands from database
    available_brands = await get_brands_from_db()
    
    # Initialize flow if not already started
    if state is None or state.flow_name != "emi":
        # Check if user has a selected car from browse flow
        # Note: This is handled by browse_car_flow when transitioning, but we check here too
        selected_car = None
        
        # Use intelligent analysis to extract information
        try:
            analysis = await analyze_emi_message(
                message=message,
                conversation_context={"step": "selecting_car", "data": {"selected_car": selected_car}},
                available_brands=available_brands,
            )
            
            # Initialize state
            conversation_manager.set_state(
                user_id,
                ConversationState(
                    user_id=user_id,
                    flow_name="emi",
                    step="selecting_car",
                    data={
                        "selected_car": selected_car,
                        "down_payment": None,
                        "tenure": None,
                    }
                )
            )
            
            # If car already selected, move to down payment
            if selected_car:
                # Update state to down_payment step
                conversation_manager.update_state(user_id, step="down_payment")
                conversation_manager.update_data(user_id, selected_car=selected_car)
                try:
                    response = await generate_emi_response(
                        message=message,
                        conversation_context={"step": "down_payment", "data": {"selected_car": selected_car}},
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    car_price = selected_car.get("price", 0)
                    return (
                        f"Great! I see you've selected the *{selected_car.get('brand', 'N/A')} {selected_car.get('model', 'N/A')}* 🚗\n\n"
                        f"Car Price: ₹{car_price:,.0f}\n\n"
                        f"To calculate your EMI, I need to know:\n"
                        f"💵 What's your down payment amount? (in rupees or lakhs)"
                    )
            else:
                # No car selected, need to search or select
                try:
                    response = await generate_emi_response(
                        message=message,
                        conversation_context={"step": "selecting_car", "data": {}},
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return (
                        "Great! I'd be happy to help you calculate EMI for your car! 💰🚗\n\n"
                        "To get started, please:\n"
                        "1️⃣ Browse and select a car first, OR\n"
                        "2️⃣ Tell me which car you're interested in (brand and model)\n\n"
                        "Which option would you prefer?"
                    )
        
        except EMIAnalysisError as e:
            print(f"Analysis error: {e}")
            # Fallback
            conversation_manager.set_state(
                user_id,
                ConversationState(
                    user_id=user_id,
                    flow_name="emi",
                    step="selecting_car",
                    data={}
                )
            )
            return (
                "Great! I'd be happy to help you calculate EMI! 💰\n\n"
                "Please browse and select a car first, or tell me which car you're interested in."
            )
        except Exception as e:
            print(f"Error initializing EMI flow: {e}")
            conversation_manager.set_state(
                user_id,
                ConversationState(
                    user_id=user_id,
                    flow_name="emi",
                    step="selecting_car",
                    data={}
                )
            )
            return (
                "Great! I'd be happy to help you calculate EMI! 💰\n\n"
                "Please browse and select a car first, or tell me which car you're interested in."
            )
    
    # Continue based on current step
    state = conversation_manager.get_state(user_id)
    
    if state.step == "selecting_car":
        # User needs to select a car
        try:
            analysis = await analyze_emi_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
            )
            
            # Check if user wants to browse
            message_lower = message.lower()
            if "browse" in message_lower or "search" in message_lower or "find" in message_lower:
                return (
                    "Perfect! Let's browse cars first. 🚗\n\n"
                    "Please use the browse car feature to select a car, then we can calculate the EMI!"
                )
            
            # Try to extract car info or search
            # For now, guide user to browse
            try:
                response = await generate_emi_response(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                )
                return response
            except Exception as e:
                print(f"Error generating response: {e}")
                return (
                    "To calculate EMI, I need you to select a car first. 🚗\n\n"
                    "Would you like to:\n"
                    "1️⃣ Browse available cars\n"
                    "2️⃣ Tell me the car brand and model\n\n"
                    "Which option do you prefer?"
                )
        
        except EMIAnalysisError as e:
            print(f"Analysis error in selecting_car: {e}")
            return (
                "To calculate EMI, please first browse and select a car, or tell me which car you're interested in."
            )
        except Exception as e:
            print(f"Error in selecting_car step: {e}")
            return (
                "To calculate EMI, please first browse and select a car, or tell me which car you're interested in."
            )
    
    elif state.step == "down_payment":
        # Collecting down payment
        selected_car = state.data.get("selected_car")
        
        if not selected_car:
            # Car not selected, go back
            conversation_manager.update_state(user_id, step="selecting_car")
            return "I don't see a selected car. Please select a car first."
        
        try:
            analysis = await analyze_emi_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
            )
            
            # Extract down payment
            down_payment = analysis.get("extracted_down_payment")
            if not down_payment:
                down_payment = extract_down_payment_from_message(message)
            
            # Handle change intent
            user_intent = analysis.get("user_intent", "").lower()
            if "changing_criteria" in user_intent or "change" in message.lower():
                conversation_manager.update_state(user_id, step="selecting_car")
                conversation_manager.update_data(user_id, selected_car=None, down_payment=None)
                try:
                    response = await generate_emi_response(
                        message=message,
                        conversation_context={"step": "selecting_car", "data": {}},
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                return "No problem! Let's start over. Please select a car first."
            
            if down_payment:
                car_price = selected_car.get("price", 0)
                
                # Validate down payment
                if down_payment >= car_price:
                    return (
                        f"Your down payment of ₹{down_payment:,.0f} is more than the car price of ₹{car_price:,.0f}. "
                        f"Please enter a lower down payment amount."
                    )
                elif down_payment < 0:
                    return "Please enter a valid down payment amount (greater than 0)."
                
                # Store down payment and show EMI options
                conversation_manager.update_data(user_id, down_payment=down_payment)
                conversation_manager.update_state(user_id, step="selecting_tenure")
                
                return format_emi_options(selected_car, down_payment)
            else:
                # Ask for down payment
                try:
                    response = await generate_emi_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": state.data
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    car_price = selected_car.get("price", 0)
                    return (
                        f"Perfect! The car price is ₹{car_price:,.0f}. 💰\n\n"
                        f"What's your down payment amount? (You can specify in rupees or lakhs, e.g., '2 lakh' or '200000')"
                    )
        
        except EMIAnalysisError as e:
            print(f"Analysis error in down_payment: {e}")
            # Fallback extraction
            down_payment = extract_down_payment_from_message(message)
            if down_payment:
                car_price = selected_car.get("price", 0)
                if down_payment >= car_price:
                    return f"Down payment cannot be more than car price. Please enter a lower amount."
                conversation_manager.update_data(user_id, down_payment=down_payment)
                conversation_manager.update_state(user_id, step="selecting_tenure")
                return format_emi_options(selected_car, down_payment)
            else:
                car_price = selected_car.get("price", 0)
                return f"What's your down payment amount? (Car price: ₹{car_price:,.0f})"
        except Exception as e:
            print(f"Error in down_payment step: {e}")
            # Fallback extraction
            down_payment = extract_down_payment_from_message(message)
            if down_payment:
                car_price = selected_car.get("price", 0)
                if down_payment >= car_price:
                    return f"Down payment cannot be more than car price. Please enter a lower amount."
                conversation_manager.update_data(user_id, down_payment=down_payment)
                conversation_manager.update_state(user_id, step="selecting_tenure")
                return format_emi_options(selected_car, down_payment)
            else:
                car_price = selected_car.get("price", 0)
                return f"What's your down payment amount? (Car price: ₹{car_price:,.0f})"
    
    elif state.step == "selecting_tenure":
        # User selecting tenure
        selected_car = state.data.get("selected_car")
        down_payment = state.data.get("down_payment")
        
        if not selected_car or not down_payment:
            conversation_manager.update_state(user_id, step="down_payment")
            return "I need the car and down payment information. Let's start over."
        
        try:
            analysis = await analyze_emi_message(
                message=message,
                conversation_context={
                    "step": state.step,
                    "data": state.data
                },
                available_brands=available_brands,
            )
            
            # Extract tenure
            tenure = analysis.get("extracted_tenure")
            
            # Also check if user selected a number (could be tenure option)
            message_lower = message.lower().strip()
            if not tenure:
                # Try to extract number
                try:
                    number = int(message_lower)
                    if number in EMI_TENURE_OPTIONS:
                        tenure = number
                except ValueError:
                    pass
            
            # Handle change intent
            user_intent = analysis.get("user_intent", "").lower()
            if "changing_criteria" in user_intent or "change" in message.lower():
                conversation_manager.update_state(user_id, step="down_payment")
                conversation_manager.update_data(user_id, tenure=None)
                try:
                    response = await generate_emi_response(
                        message=message,
                        conversation_context={"step": "down_payment", "data": state.data},
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                return "No problem! What down payment amount would you like to use?"
            
            if tenure and tenure in EMI_TENURE_OPTIONS:
                # Calculate and show EMI
                car_price = selected_car.get("price", 0)
                loan_amount = car_price - down_payment
                
                emi_data = calculate_emi(loan_amount, DEFAULT_INTEREST_RATE, tenure)
                
                # Store results
                conversation_manager.update_data(user_id, tenure=tenure, emi_data=emi_data)
                conversation_manager.update_state(user_id, step="showing_emi")
                
                return format_emi_result(selected_car, down_payment, tenure, emi_data)
            else:
                # Invalid tenure
                try:
                    response = await generate_emi_response(
                        message=message,
                        conversation_context={
                            "step": state.step,
                            "data": state.data
                        },
                        analysis_result=analysis,
                        available_brands=available_brands,
                    )
                    return response
                except Exception as e:
                    print(f"Error generating response: {e}")
                    return (
                        f"Please select a valid tenure option: {', '.join(map(str, EMI_TENURE_OPTIONS))} months\n\n"
                        f"Or type 'change' to modify your down payment."
                    )
        
        except EMIAnalysisError as e:
            print(f"Analysis error in selecting_tenure: {e}")
            # Fallback
            try:
                tenure = int(message_lower)
                if tenure in EMI_TENURE_OPTIONS:
                    car_price = selected_car.get("price", 0)
                    loan_amount = car_price - down_payment
                    emi_data = calculate_emi(loan_amount, DEFAULT_INTEREST_RATE, tenure)
                    conversation_manager.update_data(user_id, tenure=tenure, emi_data=emi_data)
                    conversation_manager.update_state(user_id, step="showing_emi")
                    return format_emi_result(selected_car, down_payment, tenure, emi_data)
            except ValueError:
                pass
            except Exception as e:
                print(f"Error calculating EMI: {e}")
            
            return (
                f"Please select a tenure from the options: {', '.join(map(str, EMI_TENURE_OPTIONS))} months"
            )
        except Exception as e:
            print(f"Error in selecting_tenure step: {e}")
            # Fallback
            try:
                tenure = int(message_lower)
                if tenure in EMI_TENURE_OPTIONS:
                    car_price = selected_car.get("price", 0)
                    loan_amount = car_price - down_payment
                    emi_data = calculate_emi(loan_amount, DEFAULT_INTEREST_RATE, tenure)
                    conversation_manager.update_data(user_id, tenure=tenure, emi_data=emi_data)
                    conversation_manager.update_state(user_id, step="showing_emi")
                    return format_emi_result(selected_car, down_payment, tenure, emi_data)
            except (ValueError, Exception) as e:
                print(f"Error processing tenure: {e}")
            
            return (
                f"Please select a tenure from the options: {', '.join(map(str, EMI_TENURE_OPTIONS))} months"
            )
    
    elif state.step == "showing_emi":
        # Handle post-EMI actions
        message_lower = message.lower().strip()
        
        if "1" in message_lower or "another" in message_lower or "new" in message_lower or "calculate another" in message_lower:
            # Calculate for another car
            conversation_manager.update_state(user_id, step="selecting_car")
            conversation_manager.update_data(user_id, selected_car=None, down_payment=None, tenure=None, emi_data=None)
            return "Great! Let's calculate EMI for another car! 🚗💰\n\nPlease select a car first."
        
        elif "2" in message_lower or "change" in message_lower or "modify" in message_lower:
            # Change down payment or tenure
            conversation_manager.update_state(user_id, step="down_payment")
            conversation_manager.update_data(user_id, tenure=None, emi_data=None)
            return "No problem! What down payment amount would you like to use?"
        
        elif "3" in message_lower or "information" in message_lower or "details" in message_lower or "more" in message_lower:
            # More information
            emi_data = state.data.get("emi_data", {})
            if emi_data:
                return (
                    f"*EMI Details:*\n\n"
                    f"• Interest Rate: {DEFAULT_INTEREST_RATE}% per annum\n"
                    f"• Monthly Interest Rate: {DEFAULT_INTEREST_RATE/12:.2f}%\n"
                    f"• Calculation Method: Standard EMI formula\n\n"
                    f"*Note:* Final EMI may vary based on:\n"
                    f"• Your credit score\n"
                    f"• Bank policies\n"
                    f"• Current market rates\n"
                    f"• Additional charges\n\n"
                    f"For exact EMI, please contact our finance team!"
                )
            else:
                return "I don't have the EMI details. Let's calculate again!"
        
        else:
            # Generate intelligent response
            try:
                analysis = await analyze_emi_message(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    available_brands=available_brands,
                )
                
                response = await generate_emi_response(
                    message=message,
                    conversation_context={
                        "step": state.step,
                        "data": state.data
                    },
                    analysis_result=analysis,
                    available_brands=available_brands,
                )
                return response
            except EMIAnalysisError as e:
                print(f"Analysis error in showing_emi: {e}")
                return "Would you like to:\n1️⃣ Calculate EMI for another car\n2️⃣ Change down payment or tenure\n3️⃣ Get more information"
            except Exception as e:
                print(f"Error generating response: {e}")
                return "Would you like to:\n1️⃣ Calculate EMI for another car\n2️⃣ Change down payment or tenure\n3️⃣ Get more information"
    
    return "I'm not sure how to help with that. Could you please rephrase?"

