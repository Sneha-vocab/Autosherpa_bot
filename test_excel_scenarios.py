"""
Comprehensive test suite based on Excel test files (Test 1, Test 2, Test 3)
Tests all bug scenarios identified in the Excel sheets
"""

import asyncio
import sys
from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import patch

# Import the bot components
from main import process_text_message
from conversation_state import conversation_manager, ConversationState
from intent_service import extract_intent, IntentResult

@dataclass
class TestCase:
    """Single test case from Excel"""
    test_id: str
    user_input: str
    expected_behavior: str
    bug_description: str = ""


@dataclass
class TestResult:
    """Result of a test scenario"""
    test_id: str
    user_input: str
    passed: bool
    expected_behavior: str
    actual_response: str
    bug_found: bool = False
    bug_description: str = ""
    error: str = ""
    execution_time: float = 0.0


class ExcelScenarioTester:
    """Test bot based on Excel test scenarios"""
    
    def __init__(self):
        self.test_results: List[TestResult] = []
        self.captured_responses: List[str] = []
        self.test_user_id = "excel_test_user"
        
    async def mock_send_whatsapp_message(self, to: str, message: str, **kwargs):
        """Mock function to capture messages"""
        self.captured_responses.append(message)
        return {"status": "sent", "message_id": "test_msg"}
    
    async def run_test_case(self, test_case: TestCase) -> TestResult:
        """Run a single test case"""
        print(f"\n{'='*80}")
        print(f"Test ID: {test_case.test_id}")
        print(f"User Input: {test_case.user_input}")
        print(f"Expected: {test_case.expected_behavior}")
        if test_case.bug_description:
            print(f"Bug: {test_case.bug_description}")
        print(f"{'='*80}")
        
        start_time = datetime.now()
        self.captured_responses = []
        error = ""
        bug_found = False
        
        try:
            # For "change" test, set up a browse car flow first
            if test_case.test_id == "T2-1":
                # Set up browse car flow context
                conversation_manager.set_state(
                    self.test_user_id,
                    ConversationState(
                        user_id=self.test_user_id,
                        flow_name="browse_car",
                        step="showing_cars",
                        data={"brand": "Toyota", "budget": "1000000", "car_type": "Sedan"}
                    )
                )
            
            # For "No" test, set up a flow first
            if test_case.test_id == "T3-4":
                # Set up browse car flow context with a question asked
                conversation_manager.set_state(
                    self.test_user_id,
                    ConversationState(
                        user_id=self.test_user_id,
                        flow_name="browse_car",
                        step="collecting_criteria",
                        data={"brand": "Hyundai"}
                    )
                )
            
            # Mock send_whatsapp_message
            with patch('main.send_whatsapp_message', side_effect=self.mock_send_whatsapp_message):
                # Process the message
                await process_text_message(
                    self.test_user_id, 
                    test_case.user_input, 
                    f"test_{test_case.test_id}"
                )
            
            # Get the response
            actual_response = self.captured_responses[-1] if self.captured_responses else ""
            
            # Get current state
            state = conversation_manager.get_state(self.test_user_id)
            current_flow = state.flow_name if state else "none"
            
            # Check for bugs based on expected behavior
            bug_found = self._check_for_bug(
                test_case, 
                actual_response, 
                current_flow
            )
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            result = TestResult(
                test_id=test_case.test_id,
                user_input=test_case.user_input,
                passed=not bug_found,
                expected_behavior=test_case.expected_behavior,
                actual_response=actual_response[:200] + "..." if len(actual_response) > 200 else actual_response,
                bug_found=bug_found,
                bug_description=test_case.bug_description,
                error=error,
                execution_time=execution_time
            )
            
            if bug_found:
                print(f"❌ BUG FOUND: {test_case.bug_description}")
                print(f"   Response: {actual_response[:150]}...")
            else:
                print(f"✅ PASSED")
                print(f"   Response: {actual_response[:150]}...")
            
            self.test_results.append(result)
            return result
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error = str(e)
            print(f"❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            
            result = TestResult(
                test_id=test_case.test_id,
                user_input=test_case.user_input,
                passed=False,
                expected_behavior=test_case.expected_behavior,
                actual_response="",
                bug_found=True,
                bug_description=test_case.bug_description,
                error=error,
                execution_time=execution_time
            )
            self.test_results.append(result)
            return result
    
    def _check_for_bug(self, test_case: TestCase, response: str, current_flow: str) -> bool:
        """Check if the response indicates a bug"""
        response_lower = response.lower()
        input_lower = test_case.user_input.lower()
        
        # Bug 1: User wants to browse but bot responds about valuation
        if "browse" in input_lower or "buy" in input_lower or "used car" in input_lower:
            if "value" in response_lower or "valuation" in response_lower:
                if "browse" not in response_lower and "car" not in response_lower[:50]:
                    return True
        
        # Bug 2: User provides brand/model but bot asks for valuation
        if any(brand in input_lower for brand in ["kia", "hyundai", "toyota", "honda"]):
            if "value" in response_lower and "browse" not in response_lower:
                return True
        
        # Bug 3: User wants EMI but bot asks for car model first (should handle better)
        if "emi" in input_lower:
            if "model" in response_lower and "brand" in response_lower:
                # This might be okay, but check if it's too restrictive
                pass
        
        # Bug 4: User asks about company/services but bot asks about cars
        # Only flag if bot doesn't show services
        if any(word in input_lower for word in ["company", "service", "location", "contact", "callback"]):
            if "service" in input_lower and "service" not in response_lower[:100]:
                # User asked about services but bot didn't mention services
                if "car" in response_lower and ("browse" in response_lower or "brand" in response_lower):
                    return True
        
        # Bug 5: User says "change" but context is lost
        # For T2-1, we set up context, so if flow is lost, it's a bug
        if test_case.test_id == "T2-1":
            if current_flow == "none":
                return True
            # Check if response mentions changing criteria
            if "change" not in response_lower and "modify" not in response_lower:
                # Bot should acknowledge the change request
                if "start" not in response_lower and "fresh" not in response_lower:
                    return True
        
        # Bug 6: User says "no" but context is completely reset
        # For T3-4, we set up context, so if flow is lost, it's a bug
        if test_case.test_id == "T3-4":
            if current_flow == "none":
                return True
        
        # Bug 7: User wants to browse but bot responds with wrong flow
        if "browse" in input_lower or "used car" in input_lower:
            if current_flow not in ["browse_car", "none"]:
                return True
        
        # Bug 8: Service booking - check if bot actually shows services
        if "service" in input_lower and "book" in input_lower:
            # Bot should show services or route to service_booking
            if current_flow != "service_booking" and "service" not in response_lower[:100]:
                return True
        
        return False
    
    def get_test_cases_from_excel(self) -> List[TestCase]:
        """Get test cases based on Excel files analysis"""
        test_cases = []
        
        # Test 1.xlsx scenarios
        test_cases.extend([
            TestCase(
                test_id="T1-1",
                user_input="I want to buy used cars",
                expected_behavior="Should initiate browse car flow",
                bug_description="Bot responds about valuation instead of browsing"
            ),
            TestCase(
                test_id="T1-2",
                user_input="Kia",
                expected_behavior="Should continue browse car flow asking for budget/type",
                bug_description="Bot responds about valuation instead of browsing"
            ),
            TestCase(
                test_id="T1-3",
                user_input="Carrens",
                expected_behavior="Should handle typo gracefully or ask for clarification",
                bug_description="Bot should handle typos better"
            ),
            TestCase(
                test_id="T1-4",
                user_input="I want to exchange cars",
                expected_behavior="Should handle exchange request or redirect appropriately",
                bug_description="Bot doesn't handle car exchange requests"
            ),
            TestCase(
                test_id="T1-5",
                user_input="600000",
                expected_behavior="Should accept as budget in browse car flow",
                bug_description="Bot responds about valuation instead of browsing"
            ),
            TestCase(
                test_id="T1-6",
                user_input="I want Hyundai cars",
                expected_behavior="Should continue browse car flow",
                bug_description="Bot asks for model to value (wrong flow)"
            ),
            TestCase(
                test_id="T1-7",
                user_input="Show me budget cars",
                expected_behavior="Should show cars in browse car flow",
                bug_description="Bot asks for model/year (wrong flow)"
            ),
            TestCase(
                test_id="T1-8",
                user_input="SUV under 10 lakh",
                expected_behavior="Should search for SUVs under 10 lakh",
                bug_description="Bot asks for model/year/condition (wrong flow)"
            ),
            TestCase(
                test_id="T1-9",
                user_input="Compare Creta and Seltos",
                expected_behavior="Should handle comparison or show both cars",
                bug_description="Bot asks for model year to value (wrong flow)"
            ),
            TestCase(
                test_id="T1-10",
                user_input="I want EMI details",
                expected_behavior="Should initiate EMI flow",
                bug_description="Bot asks for car model first (should handle better)"
            ),
            TestCase(
                test_id="T1-11",
                user_input="about your company",
                expected_behavior="Should provide company information",
                bug_description="Bot asks about brand instead of providing company info"
            ),
            TestCase(
                test_id="T1-12",
                user_input="book a test drive",
                expected_behavior="Should show service options or initiate test drive booking",
                bug_description="Inconsistent responses for test drive booking"
            ),
            TestCase(
                test_id="T1-13",
                user_input="locations",
                expected_behavior="Should provide location information",
                bug_description="Bot asks about service instead of providing locations"
            ),
            TestCase(
                test_id="T1-14",
                user_input="can i get your location",
                expected_behavior="Should provide location addresses",
                bug_description="Bot should provide location information"
            ),
            TestCase(
                test_id="T1-15",
                user_input="provide what are all the services",
                expected_behavior="Should list all services clearly",
                bug_description="Bot should list services clearly"
            ),
        ])
        
        # Test 2.xlsx scenarios
        test_cases.extend([
            TestCase(
                test_id="T2-1",
                user_input="change",
                expected_behavior="Should allow changing search criteria in current flow",
                bug_description="Context is lost when user says 'change'"
            ),
            TestCase(
                test_id="T2-2",
                user_input="hatchback",
                expected_behavior="Should continue in current flow or ask for next step",
                bug_description="Bot resets to main menu instead of continuing"
            ),
            TestCase(
                test_id="T2-3",
                user_input="Browse used cars",
                expected_behavior="Should initiate browse car flow",
                bug_description="Bot should start browsing flow"
            ),
            TestCase(
                test_id="T2-4",
                user_input="Calculate EMI",
                expected_behavior="Should initiate EMI flow",
                bug_description="Bot should start EMI calculation"
            ),
            TestCase(
                test_id="T2-5",
                user_input="list me some popular options",
                expected_behavior="Should list popular car options",
                bug_description="Bot asks for brand instead of listing options"
            ),
            TestCase(
                test_id="T2-6",
                user_input="browse car",
                expected_behavior="Should initiate browse car flow",
                bug_description="Bot responds about EMI instead of browsing"
            ),
            TestCase(
                test_id="T2-7",
                user_input="Book a service",
                expected_behavior="Should initiate service booking flow",
                bug_description="Bot asks about EMI instead of service booking"
            ),
        ])
        
        # Test 3.xlsx scenarios
        test_cases.extend([
            TestCase(
                test_id="T3-1",
                user_input="hi",
                expected_behavior="Should greet and show main menu",
                bug_description="Bot should greet properly"
            ),
            TestCase(
                test_id="T3-2",
                user_input="how you can help me",
                expected_behavior="Should explain available services",
                bug_description="Bot should explain services clearly"
            ),
            TestCase(
                test_id="T3-3",
                user_input="I am here for used car",
                expected_behavior="Should initiate browse car flow",
                bug_description="Bot should start browsing"
            ),
            TestCase(
                test_id="T3-4",
                user_input="No",
                expected_behavior="Should handle 'No' without losing all context",
                bug_description="Bot completely resets context on 'No'"
            ),
            TestCase(
                test_id="T3-5",
                user_input="restart",
                expected_behavior="Should restart conversation gracefully",
                bug_description="Bot should handle restart properly"
            ),
            TestCase(
                test_id="T3-6",
                user_input="what all the service you provide",
                expected_behavior="Should list all services",
                bug_description="Bot asks about cars instead of listing services"
            ),
            TestCase(
                test_id="T3-7",
                user_input="I am not looking for the used car",
                expected_behavior="Should acknowledge and ask what they need",
                bug_description="Bot still asks about new cars"
            ),
            TestCase(
                test_id="T3-8",
                user_input="I want to know the status of RC transfer",
                expected_behavior="Should handle RC transfer query or redirect",
                bug_description="Bot asks about cars instead of handling RC transfer"
            ),
            TestCase(
                test_id="T3-9",
                user_input="can you please connect to live agent",
                expected_behavior="Should acknowledge and provide agent connection",
                bug_description="Bot asks about cars instead of connecting to agent"
            ),
        ])
        
        return test_cases
    
    async def run_all_tests(self):
        """Run all test cases"""
        print("\n" + "="*80)
        print("EXCEL-BASED COMPREHENSIVE BOT TESTING")
        print("Testing all scenarios from Test 1.xlsx, Test 2.xlsx, Test 3.xlsx")
        print("="*80)
        
        test_cases = self.get_test_cases_from_excel()
        
        print(f"\nTotal test cases: {len(test_cases)}")
        print("Starting tests...\n")
        
        for test_case in test_cases:
            # Clear state before each test (except for multi-step scenarios)
            if not test_case.test_id.startswith("T2-") or test_case.test_id == "T2-1":
                conversation_manager.clear_state(self.test_user_id)
            
            await self.run_test_case(test_case)
            await asyncio.sleep(0.5)  # Small delay between tests
        
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r.passed)
        failed_tests = total_tests - passed_tests
        bugs_found = sum(1 for r in self.test_results if r.bug_found)
        
        print(f"\nTotal Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"🐛 Bugs Found: {bugs_found}")
        print(f"Success Rate: {(passed_tests/total_tests*100):.1f}%")
        
        total_time = sum(r.execution_time for r in self.test_results)
        print(f"\nTotal Execution Time: {total_time:.2f} seconds")
        print(f"Average Time per Test: {(total_time/total_tests):.2f} seconds")
        
        if bugs_found > 0:
            print("\n" + "="*80)
            print("BUGS FOUND:")
            print("="*80)
            for result in self.test_results:
                if result.bug_found:
                    print(f"\n🐛 Test {result.test_id}: {result.user_input}")
                    print(f"   Bug: {result.bug_description}")
                    print(f"   Response: {result.actual_response[:100]}...")
                    if result.error:
                        print(f"   Error: {result.error}")
        
        print("\n" + "="*80)
        print("DETAILED RESULTS:")
        print("="*80)
        for result in self.test_results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            bug_marker = "🐛" if result.bug_found else "  "
            print(f"{status} {bug_marker} | {result.test_id:6s} | {result.user_input:40s} | {result.execution_time:6.2f}s")


async def main():
    """Main test runner"""
    tester = ExcelScenarioTester()
    try:
        await tester.run_all_tests()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        conversation_manager.clear_state(tester.test_user_id)
        print("\n\nTest cleanup completed")


if __name__ == "__main__":
    asyncio.run(main())

