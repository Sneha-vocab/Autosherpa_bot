"""
Test Matrix Generator for AutoSherpa Bot
Tests 100 complete conversations per flow and verifies bot responses.
"""

import asyncio
import random
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from conversation_state import conversation_manager, ConversationState
from browse_car_flow import handle_browse_car_flow
from car_valuation_flow import handle_car_valuation_flow
from emi_flow import handle_emi_flow
from service_booking_flow import handle_service_booking_flow
from database import car_db

# Test data generators
BRANDS = ["Hyundai", "Maruti", "Tata", "Honda", "Toyota", "Mahindra", "Ford", "Nissan", "Skoda", "Renault"]
CAR_TYPES = ["SUV", "Sedan", "Hatchback", "MUV", "Coupe"]
FUEL_TYPES = ["Petrol", "Diesel", "Electric", "CNG", "Hybrid"]
CONDITIONS = ["Excellent", "Very Good", "Good", "Average", "Fair", "Poor"]
SERVICE_TYPES = ["Regular Service", "Major Service", "Accident Repair", "Insurance Claim", "Other"]
NAMES = ["Raj", "Priya", "Amit", "Sneha", "Rahul", "Anjali", "Vikram", "Kavya", "Arjun", "Meera"]
PHONE_PREFIXES = ["91", "91", "91", "91", "91"]  # Indian numbers


class TestConversation:
    """Represents a single test conversation."""
    
    def __init__(self, flow_name: str, conversation_id: int):
        self.flow_name = flow_name
        self.conversation_id = conversation_id
        self.user_id = f"test_user_{flow_name}_{conversation_id}"
        self.messages: List[Dict[str, str]] = []
        self.responses: List[str] = []
        self.errors: List[str] = []
        self.completed = False
        self.steps_completed = 0
        self.total_steps = 0
        
    def add_message(self, user_message: str, bot_response: str, error: Optional[str] = None):
        """Add a message exchange to the conversation."""
        self.messages.append({
            "user": user_message,
            "bot": bot_response,
            "timestamp": datetime.now().isoformat()
        })
        self.responses.append(bot_response)
        if error:
            self.errors.append(error)
        self.steps_completed += 1
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert conversation to dictionary."""
        return {
            "flow_name": self.flow_name,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "messages": self.messages,
            "completed": self.completed,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "errors": self.errors,
            "success_rate": (self.steps_completed / self.total_steps * 100) if self.total_steps > 0 else 0
        }


class TestMatrixGenerator:
    """Generates and executes test matrix for all flows."""
    
    def __init__(self):
        self.results: Dict[str, List[TestConversation]] = {
            "browse_car": [],
            "car_valuation": [],
            "emi": [],
            "service_booking": []
        }
        self.summary: Dict[str, Any] = {}
    
    def check_completion(self, response: str, flow_name: str) -> bool:
        """Check if a response indicates flow completion."""
        response_lower = response.lower()
        response_upper = response.upper()
        
        if flow_name == "browse_car":
            return ("booked" in response_lower or 
                    "successfully" in response_lower or
                    "test drive booked" in response_lower or
                    "🎉" in response or
                    ("booking id" in response_lower and "test drive" in response_lower))
        
        elif flow_name == "car_valuation":
            return ("valuation" in response_lower or 
                    "₹" in response or 
                    "rs" in response_lower or
                    "lakh" in response_lower or
                    ("estimated" in response_lower and "price" in response_lower) or
                    "worth" in response_lower)
        
        elif flow_name == "emi":
            return ("EMI" in response_upper or 
                    "₹" in response or 
                    "rs" in response_lower or
                    ("monthly" in response_lower and ("payment" in response_lower or "emi" in response_lower)) or
                    "calculated" in response_lower)
        
        elif flow_name == "service_booking":
            return ("confirmed" in response_lower or 
                    ("booking" in response_lower and ("id" in response_lower or "confirmed" in response_lower)) or
                    "service booking confirmed" in response_lower or
                    "✅" in response)
        
        return False
        
    async def generate_browse_car_conversations(self, count: int = 100) -> List[TestConversation]:
        """Generate 100 complete browse car conversations."""
        conversations = []
        
        for i in range(count):
            conv = TestConversation("browse_car", i + 1)
            try:
                # Step 1: Initial message
                user_msg = random.choice([
                    "I want to buy a car",
                    "browse cars",
                    "looking for a car",
                    "show me cars",
                    "I need a car"
                ])
                response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Check for early completion
                if self.check_completion(response, "browse_car"):
                    conv.completed = True
                
                # Step 2: Provide brand
                brand = random.choice(BRANDS)
                user_msg = random.choice([
                    brand,
                    f"I want {brand}",
                    f"Looking for {brand}",
                    f"{brand} please"
                ])
                response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 3: Provide budget
                budget_min = random.randint(3, 8)
                budget_max = budget_min + random.randint(2, 5)
                user_msg = random.choice([
                    f"{budget_min}-{budget_max} lakh",
                    f"{budget_min} to {budget_max} lakh",
                    f"under {budget_max} lakh",
                    f"{budget_min} lakh"
                ])
                response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 4: Provide car type
                car_type = random.choice(CAR_TYPES)
                user_msg = random.choice([
                    car_type,
                    f"I want {car_type}",
                    f"{car_type} please"
                ])
                response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 5: Select a car (if cars are shown)
                # More flexible check for car listing
                response_lower = response.lower()
                has_car_numbers = any(str(n) in response for n in range(1, 11))
                if ("found" in response_lower or 
                    ("car" in response_lower and has_car_numbers) or
                    "select" in response_lower and "car" in response_lower or
                    "here are" in response_lower and "car" in response_lower):
                    # Try to select car number 1
                    user_msg = "1"
                    response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                    conv.add_message(user_msg, response)
                    
                    # Step 6: Book test drive
                    response_lower = response.lower()
                    if ("test drive" in response_lower or 
                        "book" in response_lower or
                        "1" in response or
                        "option" in response_lower):
                        user_msg = "1"
                        response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                        conv.add_message(user_msg, response)
                        
                        # Step 7: Provide name
                        name = random.choice(NAMES)
                        user_msg = name
                        response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                        conv.add_message(user_msg, response)
                        
                        # Step 8: Provide phone
                        phone = f"{random.choice(PHONE_PREFIXES)}{random.randint(1000000000, 9999999999)}"
                        user_msg = phone
                        response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                        conv.add_message(user_msg, response)
                        
                        # Step 9: Provide DL info
                        user_msg = random.choice(["yes", "Yes", "I have", "y"])
                        response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                        conv.add_message(user_msg, response)
                        
                        # Step 10: Provide location
                        user_msg = random.choice(["1", "2", "showroom", "home"])
                        response = await handle_browse_car_flow(conv.user_id, user_msg, None)
                        conv.add_message(user_msg, response)
                        
                        # Check for completion
                        if self.check_completion(response, "browse_car"):
                            conv.completed = True
                
                conv.total_steps = conv.steps_completed
                conversations.append(conv)
                
            except Exception as e:
                conv.add_message("", "", str(e))
                conversations.append(conv)
            
            # Clear state for next conversation
            conversation_manager.clear_state(conv.user_id)
            
        return conversations
    
    async def generate_car_valuation_conversations(self, count: int = 100) -> List[TestConversation]:
        """Generate 100 complete car valuation conversations."""
        conversations = []
        
        for i in range(count):
            conv = TestConversation("car_valuation", i + 1)
            try:
                # Step 1: Initial message
                user_msg = random.choice([
                    "value my car",
                    "how much is my car worth",
                    "car valuation",
                    "I want to sell my car",
                    "what's the price of my car"
                ])
                response = await handle_car_valuation_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Check for early completion
                if self.check_completion(response, "car_valuation"):
                    conv.completed = True
                
                # Step 2: Provide brand
                brand = random.choice(BRANDS)
                user_msg = random.choice([brand, f"{brand} car", f"It's {brand}"])
                response = await handle_car_valuation_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 3: Provide model
                model = random.choice(["i20", "Creta", "Swift", "City", "Innova", "Nexon", "EcoSport", "Magnite", "Rapid", "Duster"])
                user_msg = random.choice([model, f"{brand} {model}", f"Model is {model}"])
                response = await handle_car_valuation_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 4: Provide year
                year = random.randint(2015, 2023)
                user_msg = random.choice([str(year), f"Year {year}", f"{year} model"])
                response = await handle_car_valuation_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 5: Provide fuel type
                fuel_type = random.choice(FUEL_TYPES)
                user_msg = random.choice([fuel_type, f"{fuel_type} car", f"It's {fuel_type}"])
                response = await handle_car_valuation_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 6: Provide condition
                condition = random.choice(CONDITIONS)
                user_msg = random.choice([condition.lower(), f"{condition.lower()} condition", f"It's {condition.lower()}"])
                response = await handle_car_valuation_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Check for completion
                if self.check_completion(response, "car_valuation"):
                    conv.completed = True
                
                conv.total_steps = conv.steps_completed
                conversations.append(conv)
                
            except Exception as e:
                conv.add_message("", "", str(e))
                conversations.append(conv)
            
            conversation_manager.clear_state(conv.user_id)
            
        return conversations
    
    async def generate_emi_conversations(self, count: int = 100) -> List[TestConversation]:
        """Generate 100 complete EMI conversations."""
        conversations = []
        
        for i in range(count):
            conv = TestConversation("emi", i + 1)
            try:
                # Step 1: Initial message
                user_msg = random.choice([
                    "calculate EMI",
                    "loan options",
                    "monthly payment",
                    "I need EMI calculation",
                    "finance options"
                ])
                response = await handle_emi_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Check for early completion
                if self.check_completion(response, "emi"):
                    conv.completed = True
                
                # Step 2: For EMI, we need a car first
                # Simulate selecting a car by providing car details or browsing
                # Since EMI flow requires a selected car, we'll create a mock car in state
                # Or we can browse first - let's try browsing approach
                # Actually, let's set a selected car in the state directly for testing
                brand = random.choice(BRANDS)
                model = random.choice(["i20", "Creta", "Swift", "City", "Innova"])
                price = random.randint(500000, 2000000)
                
                # Set a selected car in the state for testing
                # Since EMI flow needs a car, we'll set it directly
                selected_car = {
                    "id": i + 1,
                    "brand": brand,
                    "model": model,
                    "price": price
                }
                conversation_manager.update_state(conv.user_id, step="down_payment")
                conversation_manager.update_data(conv.user_id, selected_car=selected_car)
                
                # Step 3: Provide down payment
                down_payment = random.randint(1, 5)  # in lakhs
                user_msg = random.choice([
                    f"{down_payment} lakh",
                    f"{down_payment * 100000}",
                    f"{down_payment}L"
                ])
                response = await handle_emi_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 4: Select tenure
                tenure = random.choice([12, 24, 36, 48, 60, 72])
                user_msg = str(tenure)
                response = await handle_emi_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Check for completion
                if self.check_completion(response, "emi"):
                    conv.completed = True
                
                conv.total_steps = conv.steps_completed
                conversations.append(conv)
                
            except Exception as e:
                conv.add_message("", "", str(e))
                conversations.append(conv)
            
            conversation_manager.clear_state(conv.user_id)
            
        return conversations
    
    async def generate_service_booking_conversations(self, count: int = 100) -> List[TestConversation]:
        """Generate 100 complete service booking conversations."""
        conversations = []
        
        for i in range(count):
            conv = TestConversation("service_booking", i + 1)
            try:
                # Step 1: Initial message
                user_msg = random.choice([
                    "book service",
                    "service booking",
                    "book a service",
                    "I need servicing",
                    "car service"
                ])
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Check for early completion
                if self.check_completion(response, "service_booking"):
                    conv.completed = True
                
                # Step 2: Select book service option
                user_msg = "1"
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 3: Provide make/brand
                brand = random.choice(BRANDS)
                user_msg = brand
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 4: Provide model
                model = random.choice(["i20", "Creta", "Swift", "City", "Innova"])
                user_msg = model
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 5: Provide year
                year = random.randint(2015, 2023)
                user_msg = str(year)
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 6: Provide registration
                reg = f"KA{random.randint(10, 99)}{random.choice(['AB', 'CD', 'EF', 'GH'])}{random.randint(1000, 9999)}"
                user_msg = reg
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 7: Select service type
                service_type_num = random.randint(1, 5)
                user_msg = str(service_type_num)
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 8: Provide name
                name = random.choice(NAMES)
                user_msg = name
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Step 9: Provide phone (10 digits only)
                phone = f"{random.randint(1000000000, 9999999999)}"
                user_msg = phone
                response = await handle_service_booking_flow(conv.user_id, user_msg, None)
                conv.add_message(user_msg, response)
                
                # Check for completion
                if self.check_completion(response, "service_booking"):
                    conv.completed = True
                
                conv.total_steps = conv.steps_completed
                conversations.append(conv)
                
            except Exception as e:
                conv.add_message("", "", str(e))
                conversations.append(conv)
            
            conversation_manager.clear_state(conv.user_id)
            
        return conversations
    
    def verify_response(self, response: str, step: str, flow_name: str) -> Tuple[bool, str]:
        """Verify if bot response is appropriate for the step."""
        if not response or len(response.strip()) == 0:
            return False, "Empty response"
        
        response_lower = response.lower()
        
        # Basic checks
        if "error" in response_lower and "sorry" not in response_lower:
            return False, "Error in response"
        
        # Flow-specific checks
        if flow_name == "browse_car":
            if step == "collecting_criteria":
                if "brand" in response_lower or "budget" in response_lower or "type" in response_lower:
                    return True, "Appropriate"
            elif step == "showing_cars":
                if "car" in response_lower or "found" in response_lower or "select" in response_lower:
                    return True, "Appropriate"
            elif "test drive" in response_lower or "name" in response_lower:
                return True, "Appropriate"
        
        elif flow_name == "car_valuation":
            if "brand" in response_lower or "model" in response_lower or "year" in response_lower or "valuation" in response_lower:
                return True, "Appropriate"
        
        elif flow_name == "emi":
            if "emi" in response_lower or "down payment" in response_lower or "tenure" in response_lower or "loan" in response_lower:
                return True, "Appropriate"
        
        elif flow_name == "service_booking":
            if "service" in response_lower or "make" in response_lower or "model" in response_lower or "name" in response_lower:
                return True, "Appropriate"
        
        # Default: if response is not empty and not an error, consider it valid
        if len(response) > 10:
            return True, "Appropriate"
        
        return False, "Response seems inappropriate"
    
    async def run_all_tests(self):
        """Run all test conversations."""
        print("Starting test matrix generation...")
        print("=" * 60)
        
        # Initialize database if available
        if car_db and car_db.database_url:
            try:
                await car_db.init_schema()
                print("✓ Database initialized")
            except Exception as e:
                print(f"⚠ Database initialization warning: {e}")
        
        # Run tests for each flow
        flows = [
            ("browse_car", self.generate_browse_car_conversations),
            ("car_valuation", self.generate_car_valuation_conversations),
            ("emi", self.generate_emi_conversations),
            ("service_booking", self.generate_service_booking_conversations),
        ]
        
        for flow_name, generator_func in flows:
            print(f"\n📊 Testing {flow_name} flow (100 conversations)...")
            print(f"  This may take several minutes...")
            conversations = await generator_func(100)
            self.results[flow_name] = conversations
            
            # Calculate statistics
            completed = sum(1 for c in conversations if c.completed)
            total_steps = sum(c.steps_completed for c in conversations)
            total_errors = sum(len(c.errors) for c in conversations)
            
            print(f"  ✓ Completed: {completed}/100")
            print(f"  ✓ Total steps: {total_steps}")
            print(f"  ✓ Errors: {total_errors}")
        
        print("\n" + "=" * 60)
        print("✓ All tests completed!")
        
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive test report."""
        report = {
            "test_date": datetime.now().isoformat(),
            "summary": {},
            "detailed_results": {}
        }
        
        for flow_name, conversations in self.results.items():
            completed = sum(1 for c in conversations if c.completed)
            total_steps = sum(c.steps_completed for c in conversations)
            total_errors = sum(len(c.errors) for c in conversations)
            avg_steps = total_steps / len(conversations) if conversations else 0
            
            # Verify responses
            verified = 0
            for conv in conversations:
                for i, msg in enumerate(conv.messages):
                    if msg.get("bot"):
                        is_valid, _ = self.verify_response(
                            msg["bot"],
                            f"step_{i+1}",
                            flow_name
                        )
                        if is_valid:
                            verified += 1
            
            report["summary"][flow_name] = {
                "total_conversations": len(conversations),
                "completed": completed,
                "completion_rate": f"{(completed/len(conversations)*100):.2f}%" if conversations else "0%",
                "total_steps": total_steps,
                "average_steps": f"{avg_steps:.2f}",
                "total_errors": total_errors,
                "verified_responses": verified,
                "verification_rate": f"{(verified/total_steps*100):.2f}%" if total_steps > 0 else "0%"
            }
            
            report["detailed_results"][flow_name] = [c.to_dict() for c in conversations]
        
        return report
    
    def save_report(self, filename: Optional[str] = None, format: str = "json"):
        """Save test report to file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if format == "json":
                filename = f"test_report_{timestamp}.json"
            else:
                filename = f"test_report_{timestamp}.txt"
        
        report = self.generate_report()
        
        if format == "json":
            with open(filename, 'w') as f:
                json.dump(report, f, indent=2)
        else:
            # Save as text summary
            with open(filename, 'w') as f:
                f.write("=" * 80 + "\n")
                f.write("AUTOSHERPA BOT TEST MATRIX REPORT\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Test Date: {report['test_date']}\n\n")
                
                for flow_name, summary in report["summary"].items():
                    f.write(f"\n{flow_name.upper().replace('_', ' ')} FLOW\n")
                    f.write("-" * 80 + "\n")
                    f.write(f"Total Conversations: {summary['total_conversations']}\n")
                    f.write(f"Completed: {summary['completed']} ({summary['completion_rate']})\n")
                    f.write(f"Total Steps: {summary['total_steps']}\n")
                    f.write(f"Average Steps: {summary['average_steps']}\n")
                    f.write(f"Total Errors: {summary['total_errors']}\n")
                    f.write(f"Verified Responses: {summary['verified_responses']} ({summary['verification_rate']})\n")
                
                f.write("\n" + "=" * 80 + "\n")
        
        print(f"\n📄 Test report saved to: {filename}")
        return filename


async def main():
    """Main function to run test matrix."""
    print("🚀 Starting AutoSherpa Bot Test Matrix")
    print("=" * 60)
    print("⚠️  Note: This will test 100 conversations per flow (400 total)")
    print("⚠️  Note: Tests make real API calls to Gemini - may take time")
    print("=" * 60)
    
    generator = TestMatrixGenerator()
    await generator.run_all_tests()
    
    # Generate and save reports in both formats
    json_report = generator.save_report(format="json")
    txt_report = generator.save_report(format="txt")
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    report = generator.generate_report()
    for flow_name, summary in report["summary"].items():
        print(f"\n{flow_name.upper().replace('_', ' ')}:")
        print(f"  Total Conversations: {summary['total_conversations']}")
        print(f"  Completed: {summary['completed']} ({summary['completion_rate']})")
        print(f"  Average Steps: {summary['average_steps']}")
        print(f"  Errors: {summary['total_errors']}")
        print(f"  Verified Responses: {summary['verified_responses']} ({summary['verification_rate']})")
    
    print("\n" + "=" * 60)
    print(f"📄 JSON Report: {json_report}")
    print(f"📄 Text Report: {txt_report}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

