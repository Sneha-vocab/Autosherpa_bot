# AutoSherpa - WhatsApp AI Chatbot for Sherpa Hyundai

A conversational AI chatbot system for Sherpa Hyundai that enables customers to browse used cars, get car valuations, calculate EMI, and book services through WhatsApp. Built with FastAPI, Google Gemini AI, and PostgreSQL.

## 📋 Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Setup Instructions](#setup-instructions)
- [API Endpoints](#api-endpoints)
- [Flows](#flows)
- [Documentation](#documentation)
- [Deployment](#deployment)

## Features

- ✅ **AI-Powered Conversations** - Google Gemini LLM for intelligent message understanding
- ✅ **Browse Used Cars** - Search and browse car inventory with test drive booking
- ✅ **Car Valuation** - Get approximate car valuations based on car details
- ✅ **EMI Calculator** - Calculate EMI options for car loans
- ✅ **Service Booking** - Book car services through conversational interface
- ✅ **Orchestrator Pattern** - Central coordinator for all flows and services
- ✅ **State Management** - Track conversation progress across multiple interactions
- ✅ **Exception Handling** - Comprehensive error handling with fallback mechanisms
- ✅ **WhatsApp Integration** - Full WhatsApp Business API integration
- ✅ **PostgreSQL Database** - Persistent storage for cars, bookings, and services

## Architecture

AutoSherpa uses a **layered architecture with an orchestrator pattern**:

- **Orchestrator Layer**: Central coordinator (`process_text_message()`) routes and coordinates all flows
- **Application Layer**: Intent service, flow handlers, and AI analyzers
- **State Layer**: Conversation state management
- **Data Layer**: PostgreSQL database operations

### Complete Architecture Documentation

For detailed architecture information, see **[COMPLETE_ARCHITECTURE.md](./COMPLETE_ARCHITECTURE.md)** which includes:

- System overview and architecture layers
- Orchestrator pattern implementation
- Component architecture and data flow
- Flow architecture (Browse, Valuation, EMI, Service Booking)
- State management and database schema
- API architecture and AI integration
- Security, deployment, and scalability considerations

### Quick Architecture Overview

```
WhatsApp → FastAPI → Orchestrator → Flow Handler → AI Analyzer → Database → Response
```

**Key Components**:
- `main.py` - FastAPI app and orchestrator
- `intent_service.py` - Intent extraction and general responses
- `conversation_state.py` - State management
- `database.py` - Database operations
- Flow handlers: `browse_car_flow.py`, `car_valuation_flow.py`, `emi_flow.py`, `service_booking_flow.py`
- AI analyzers: `browse_car_analyzer.py`, `car_valuation_analyzer.py`, `emi_analyzer.py`, `service_booking_analyzer.py`

## Prerequisites

1. **Meta Developer Account**: Create an account at [developers.facebook.com](https://developers.facebook.com)
2. **WhatsApp Business Account**: Set up a WhatsApp Business Account
3. **Meta App**: Create a Meta App with WhatsApp product enabled
4. **Google Gemini API Key**: Get API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
5. **PostgreSQL Database**: PostgreSQL 12+ installed and running
6. **Python 3.8+**: Ensure Python is installed on your system

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

**Meta WhatsApp API (Required)**:
- `VERIFY_TOKEN`: A random string for webhook verification (e.g., "my_secure_token_123")
- `WEBHOOK_SECRET`: Your webhook secret from Meta App Dashboard (optional but recommended)
- `PHONE_NUMBER_ID`: Your WhatsApp Business Phone Number ID
- `ACCESS_TOKEN`: Your temporary or permanent access token
- `APP_SECRET`: Your app secret (optional)

**Google Gemini API (Required)**:
- `GOOGLE_API_KEY`: Your Google Gemini API key
- `GEMINI_MODEL`: Model name (default: "gemini-1.5-flash")

**Database (Required)**:
- `DATABASE_URL`: PostgreSQL connection string (e.g., "postgresql://user:password@host:port/database")

### 3. Get Meta API Credentials

1. Go to [Meta for Developers](https://developers.facebook.com)
2. Create a new app or select an existing one
3. Add the "WhatsApp" product to your app
4. Navigate to **WhatsApp > API Setup**
5. Copy your:
   - **Phone Number ID** (from the "From" field)
   - **Temporary Access Token** (or generate a permanent one)

### 4. Configure Webhook in Meta Dashboard

1. Go to your Meta App Dashboard
2. Navigate to **WhatsApp > Configuration**
3. Click **Edit** next to "Webhook"
4. Enter your webhook URL: `https://your-domain.com/webhook`
5. Enter your **Verify Token** (must match `VERIFY_TOKEN` in `.env`)
6. Subscribe to the following webhook fields:
   - `messages`
   - `message_status`
   - `message_reactions` (optional)
   - `message_echoes` (optional)

### 5. Run the Server

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The server will start on `http://localhost:8000`

## Testing Locally

For local testing, you'll need to expose your local server to the internet. You can use:

- **ngrok**: `ngrok http 8000`
- **localtunnel**: `lt --port 8000`
- **Cloudflare Tunnel**: `cloudflared tunnel --url http://localhost:8000`

Then use the provided public URL in your Meta webhook configuration.

## Flows

AutoSherpa supports 4 main conversational flows:

### 1. Browse Car Flow
- Search and browse used cars
- Filter by brand, budget, and car type
- Book test drives
- **Entry**: Messages like "I want to buy a car", "browse cars", "looking for a car"

### 2. Car Valuation Flow
- Get approximate car valuations
- Based on brand, model, year, fuel type, and condition
- **Entry**: Messages like "value my car", "how much is my car worth", "car valuation"

### 3. EMI Flow
- Calculate EMI for car loans
- Select car, down payment, and tenure
- View EMI options
- **Entry**: Messages like "calculate EMI", "loan options", "monthly payment"

### 4. Service Booking Flow
- Book car services
- Select service type
- Provide vehicle and customer details
- **Entry**: Messages like "book service", "service booking", "car servicing"

## API Endpoints

### `GET /`
Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "message": "WhatsApp Webhook API is running"
}
```

### `GET /webhook`
Webhook verification endpoint (called by Meta during setup).

**Query Parameters:**
- `hub.mode`: Should be "subscribe"
- `hub.verify_token`: Your verify token
- `hub.challenge`: Challenge string from Meta

**Response:** Returns the challenge string if verification succeeds.

### `POST /webhook`
Main webhook endpoint for receiving WhatsApp messages and events.

**Headers:**
- `X-Hub-Signature-256`: Webhook signature for verification (optional)

**Request Body:** JSON payload from Meta containing message/status data.

**Response:**
```json
{
  "status": "success"
}
```

## Message Types Supported

- **Text Messages**: Plain text messages
- **Images**: Image files with optional captions
- **Videos**: Video files with optional captions
- **Audio**: Audio/voice messages
- **Documents**: Document files (PDF, DOC, etc.)
- **Location**: Location coordinates
- **Contacts**: Contact cards

## Documentation

- **[COMPLETE_ARCHITECTURE.md](./COMPLETE_ARCHITECTURE.md)** - Comprehensive architecture documentation
  - System overview and architecture layers
  - Orchestrator pattern implementation
  - Component and data flow architecture
  - Flow architecture details
  - State management and database schema
  - Security, deployment, and scalability

- **Implementation Docs**:
  - `BROWSE_CAR_IMPLEMENTATION.md` - Browse car flow implementation
  - `CAR_VALUATION_IMPLEMENTATION.md` - Car valuation flow implementation
  - `EMI_FLOW_IMPLEMENTATION.md` - EMI flow implementation

## Security Best Practices

1. **Always use HTTPS** in production
2. **Enable signature verification** by setting `WEBHOOK_SECRET`
3. **Use environment variables** for sensitive credentials
4. **Rotate access tokens** regularly
5. **Validate phone numbers** before processing
6. **Rate limit** your endpoints to prevent abuse

## Production Deployment

1. Use a production ASGI server like Gunicorn with Uvicorn workers:
   ```bash
   gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

2. Set up proper logging and monitoring

3. Use a reverse proxy (Nginx) for SSL termination

4. Configure firewall rules to restrict access

5. Set up automated backups

## Troubleshooting

### Webhook Verification Fails
- Ensure `VERIFY_TOKEN` in `.env` matches the token in Meta Dashboard
- Check that the webhook URL is accessible from the internet
- Verify the endpoint returns the challenge string correctly

### Messages Not Received
- Check that webhook fields are subscribed in Meta Dashboard
- Verify your phone number is approved for sending messages
- Check server logs for errors
- Ensure your access token is valid and has necessary permissions

### Signature Verification Fails
- Ensure `WEBHOOK_SECRET` matches the secret in Meta Dashboard
- Check that the raw request body is being used for verification
- Verify the signature header format: `sha256=<hash>`

## Resources

- [Meta WhatsApp Business API Documentation](https://developers.facebook.com/docs/whatsapp)
- [Google Gemini API Documentation](https://ai.google.dev/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Webhook Security Best Practices](https://developers.facebook.com/docs/graph-api/webhooks/getting-started#security)

## Project Structure

```
final_autosherpa/
├── main.py                          # FastAPI app, orchestrator, webhook handlers
├── intent_service.py                # Intent extraction & general responses
├── conversation_state.py             # State management
├── database.py                      # Database operations
├── browse_car_flow.py               # Browse car flow handler
├── browse_car_analyzer.py           # Browse car AI analyzer
├── car_valuation_flow.py             # Car valuation flow handler
├── car_valuation_analyzer.py         # Valuation AI analyzer
├── emi_flow.py                       # EMI flow handler
├── emi_analyzer.py                   # EMI AI analyzer
├── service_booking_flow.py           # Service booking flow handler
├── service_booking_analyzer.py       # Service booking AI analyzer
├── requirements.txt                  # Python dependencies
├── README.md                         # This file
└── COMPLETE_ARCHITECTURE.md          # Complete architecture documentation
```

## License

MIT License

# Autosherpa_bot
