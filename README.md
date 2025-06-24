# Frappe AI - WhatsApp AI Integration

**Connecting AI to Sentra Travel Services**

A Frappe app that integrates WhatsApp conversations with AI-powered responses using Claude API and the [Frappe MCP Server](https://github.com/appliedrelevance/frappe_mcp_server).

## Architecture

```
WhatsApp Message (Incoming) → frappe_ai (Hook) → Claude API (with MCP access) → Response → WhatsApp Message (Outgoing)
```

### Components:

1. **frappe_whatsapp**: Existing app that handles WhatsApp Business API integration
2. **frappe-mcp-server**: Separate Node.js MCP server providing AI-powered Frappe data access (stdio protocol)
3. **frappe_ai**: This app that orchestrates AI responses
4. **Claude API**: Anthropic's Claude API with MCP protocol support

## Key Features

- **Automatic AI Responses**: All incoming WhatsApp messages trigger intelligent AI responses
- **Context-Aware**: Maintains conversation history and customer context
- **Business Intelligence**: Access to Lead, Trip, and Itinerary data via MCP server
- **Smart Lead Management**: Automatic lead creation for new customers
- **Configurable**: Easy setup and testing through AI Settings

## Installation

### Prerequisites

1. **Frappe WhatsApp app** must be installed and configured
2. **Frappe MCP Server** must be running separately
3. **Claude API key** from Anthropic

### Setup Steps

1. **Install the app**:

   ```bash
   cd $PATH_TO_YOUR_BENCH
   bench get-app https://github.com/your-repo/frappe_ai --branch develop
   bench install-app frappe_ai
   ```

2. **Configure AI Settings**:

   - Go to AI Settings in desk
   - Enable AI Processing
   - Add your Claude API Key
   - Configure model and parameters

3. **Set up MCP Server** (runs separately):

   ```bash
   npm install -g frappe-mcp-server
   ```

4. **Run MCP Server**:

   ```bash
   FRAPPE_URL=http://sentra.localhost:8000 \
   FRAPPE_API_KEY=your_api_key \
   FRAPPE_API_SECRET=your_api_secret \
   npx frappe-mcp-server
   ```

5. **Configure Claude with MCP** (in Claude Desktop):
   ```json
   {
     "mcpServers": {
       "frappe": {
         "command": "npx",
         "args": ["frappe-mcp-server"],
         "env": {
           "FRAPPE_URL": "http://sentra.localhost:8000",
           "FRAPPE_API_KEY": "your_api_key",
           "FRAPPE_API_SECRET": "your_api_secret"
         }
       }
     }
   }
   ```

## How It Works

### Message Processing Flow

1. **WhatsApp Message Received**: `frappe_whatsapp` creates incoming message record
2. **AI Hook Triggered**: `frappe_ai.ai_processor.process_whatsapp_message` is called
3. **Context Gathering**: System retrieves:
   - Conversation history (last 10 messages)
   - Customer data (Lead, Trips, Itineraries)
   - Business context
4. **AI Processing**: Claude API is called with:
   - System prompt with business context
   - Conversation history
   - Customer context
   - Access to MCP server for live data
5. **Response Generation**: Claude generates contextual response using MCP tools
6. **WhatsApp Response**: System creates outgoing WhatsApp message

### Business Logic

#### Customer Recognition

- Matches phone numbers across different formats
- Links conversations to existing leads/trips
- Creates new leads automatically for unknown customers

#### AI Capabilities (via MCP Server)

- Look up customer information
- Check trip status and details
- Update customer records
- Create new leads or trips
- Access detailed itinerary information
- Generate travel recommendations

#### Lead Creation Rules

- **Trigger**: New customer sends any message
- **Required Fields**: `first_name`, `mobile_number`, `source="WhatsApp"`, `status="Lead"`

## Configuration

### AI Settings DocType

Access via: **AI Settings** (Single DocType)

**Core Settings**:

- `enable_ai_processing`: Turn AI responses on/off
- `claude_api_key`: Your Anthropic API key
- `claude_model`: Model selection (Sonnet, Haiku, Opus)
- `max_tokens`: Response length limit
- `fallback_message`: Error response message

**Testing Features**:

- Test phone number and message
- Real-time AI response testing
- MCP server status checking

### Phone Number Handling

The system handles multiple phone number formats:

- `919677018116` (stored format)
- `+919677018116` (international)
- `9677018116` (without country code)
- Various WhatsApp formats

## MCP Server Integration

### What is the MCP Server?

The [Frappe MCP Server](https://github.com/appliedrelevance/frappe_mcp_server) is a **separate Node.js application** that implements the Model Context Protocol (MCP). It provides Claude with **real-time access** to your Frappe data.

### Key MCP Tools Available to Claude:

- `create_document`: Create new documents in Frappe
- `get_document`: Retrieve documents from Frappe
- `update_document`: Update existing documents
- `list_documents`: List documents with filters
- `get_doctype_schema`: Get DocType schema and field definitions
- `find_doctypes`: Search for DocTypes

### MCP Configuration:

The MCP server uses environment variables:

- `FRAPPE_URL`: Your Frappe instance URL
- `FRAPPE_API_KEY`: Frappe API key (required)
- `FRAPPE_API_SECRET`: Frappe API secret (required)

## Testing

### Via AI Settings

1. Go to **AI Settings**
2. Enter test phone number (e.g., "919677018116")
3. Enter test message (e.g., "Hello, I need help with my trip")
4. Click **Test AI Response**
5. View generated response

### Via WhatsApp Message

Create a test WhatsApp Message record:

```python
frappe.get_doc({
    "doctype": "WhatsApp Message",
    "type": "Incoming",
    "from": "919677018116",
    "message": "Hello, I need help with my trip",
    "profile_name": "Test Customer",
    "content_type": "text"
}).save()
```

## Error Handling

### Robust Error Management:

- **MCP Server Down**: Falls back to basic response
- **Claude API Issues**: Uses fallback message
- **Invalid Phone Formats**: Tries multiple variants
- **Missing Data**: Graceful degradation

### Logging:

- All operations logged to `frappe_ai` logger
- Error details captured for debugging
- Success/failure tracking

## Business Context Integration

### Sentra Travel Services Context:

The AI understands:

- **Company**: Sentra Travel Services
- **Services**: Travel planning, hotel bookings, trip management
- **Communication**: WhatsApp Business channel
- **Data Models**: Lead → Trip → Itinerary workflow

### Customer Journey Support:

1. **New Inquiry**: Create lead, gather requirements
2. **Trip Planning**: Access trip details, provide updates
3. **Booking Support**: Check itinerary status, modify bookings
4. **Customer Service**: Address concerns, provide information

## Development Notes

### Key Files:

- `hooks.py`: Document event hooks
- `ai_processor.py`: Core AI logic and Claude integration
- `doctype/ai_settings/`: Configuration DocType

### Dependencies:

- `anthropic>=0.25.0`: Claude API client
- Existing: `frappe_whatsapp`, `sentra` apps

### Architecture Benefits:

- **Separation of Concerns**: MCP server handles data, frappe_ai handles logic
- **Scalability**: MCP server can serve multiple AI integrations
- **Flexibility**: Easy to switch AI providers or add features
- **Maintainability**: Clear boundaries between components

## Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/frappe_ai
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

## Future Enhancements

1. **Advanced AI Rules**: Configurable response templates
2. **Analytics**: Track AI interaction success rates
3. **Multi-language**: Support for multiple languages
4. **Integration Expansion**: Connect with other channels
5. **Performance Optimization**: Caching and response improvements

## License

unlicense
