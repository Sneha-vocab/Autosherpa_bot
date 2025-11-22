# Browse Car Flow Refactoring Plan

## Problem
The current `browse_car_flow.py` has:
- Nested if/elif statements checking `state.step == "something"`
- Logic scattered across 1800+ lines
- Hard to maintain and extend
- No systematic error handling

## Solution: Dynamic Step Router

### Architecture
```
handle_browse_car_flow()
  ├─ Flow Switch Check
  ├─ Exit Request Check
  ├─ Flow Initialization
  └─ StepRouter.route()
       ├─ Check Confirmation State → confirmation_handler()
       ├─ Check Init State → init_handler()
       └─ Route to Step Handler → step_handler()
```

### Step Handlers Structure
Each step has:
1. **Main Handler**: Handles normal step logic
2. **Confirmation Handler** (optional): Handles confirmation responses
3. **Init Handler** (optional): Handles step initialization

### Steps to Refactor
1. `collecting_criteria` - Collect brand, budget, car_type
2. `showing_cars` - Display car list, handle selection
3. `car_selected` - Handle car selection actions
4. `test_drive_date` - Collect test drive date
5. `test_drive_time` - Collect test drive time
6. `test_drive_name` - Collect name (with LLM validation)
7. `test_drive_phone` - Collect phone
8. `test_drive_dl` - Collect driving license status
9. `test_drive_location` - Collect location preference
10. `test_drive_address` - Collect address (with LLM validation)
11. `test_drive_confirm` - Confirm test drive booking

### Benefits
- **Systematic**: All steps follow same pattern
- **Dynamic**: Easy to add new steps
- **Maintainable**: Each step handler is isolated
- **Error Handling**: Centralized error handling with FlowRoutingError
- **Testable**: Each handler can be tested independently

