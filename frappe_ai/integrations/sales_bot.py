import frappe
from frappe_ai.frappe_ai.doctype.sales_conversation.sales_conversation import ingest_message

def process_incoming_communication(doc, method):
    """
    This function is triggered by a hook on the Communication DocType.
    It checks if the message is incoming and from a supported channel, then passes it to the Sales Bot.
    Now handles conversation-based messages where new messages are appended to existing conversations.
    """
    print("================== SALES BOT HOOK CALLED ==================")
    print(f"--- Sales Bot Hook Triggered for Communication: {doc.name}, Method: {method} ---")
    print(f"--- Doc Type: {doc.doctype}, Medium: {doc.communication_medium} ---")
    print(f"--- Sent or Received: {doc.sent_or_received} ---")
    
    
    # CRITICAL: We only care about incoming messages from supported channels
    if doc.sent_or_received != "Received":
        print(f"--- Sales Bot Hook Skipped: Not a 'Received' message. Type is '{doc.sent_or_received}'. ---")
        return

    # Only process supported communication mediums
    supported_channels = ["WhatsApp", "Instagram", "SMS", "Phone Call"]
    if doc.communication_medium not in supported_channels:
        print(f"--- Sales Bot Hook Skipped: Unsupported medium '{doc.communication_medium}'. ---")
        return
    
    # CRITICAL: Skip if this Communication was created by the sales bot (avoid infinite loop)
    # Check if this is a bot response by looking at the reference
    if doc.reference_doctype == "Sales Conversation":
        print(f"--- Sales Bot Hook Skipped: This Communication references a Sales Conversation, likely a bot response ---")
        return

    # For our new conversation-based approach, process conversations linked to Contacts
    if doc.reference_doctype == "Contact":
        # This is a conversation document linked to a contact
        # Get identifier based on communication medium
        if doc.communication_medium == "WhatsApp":
            customer_identifier = doc.sender_phone or doc.phone_no
        elif doc.communication_medium == "Instagram":
            customer_identifier = doc.instagram
        else:
            customer_identifier = doc.sender_phone or doc.phone_no or doc.sender
        
        channel = doc.communication_medium
        
        # Extract the latest message from the conversation content
        # The content contains HTML-formatted messages, we need to extract the latest one
        if doc.content:
            print(f"--- DEBUG: Raw content length: {len(doc.content)} ---")
            print(f"--- DEBUG: Raw content preview: {doc.content[:200]}... ---")
            user_message, is_bot_message = extract_latest_message_from_content(doc.content)
            print(f"--- DEBUG: Extracted message: '{user_message}' ---")
            print(f"--- DEBUG: Is bot message: {is_bot_message} ---")
            
            # CRITICAL: Skip if the latest message is from the bot (sent by "You")
            if is_bot_message:
                print(f"--- Sales Bot Hook Skipped: Latest message is from bot (sender: 'You') ---")
                return
        else:
            user_message = None
            print(f"--- DEBUG: No content in document ---")
            
    elif not doc.reference_doctype:
        # This might be an unlinked conversation
        # Get identifier based on communication medium
        if doc.communication_medium == "WhatsApp":
            customer_identifier = doc.sender_phone or doc.phone_no
        elif doc.communication_medium == "Instagram":
            customer_identifier = doc.instagram
        else:
            customer_identifier = doc.sender_phone or doc.phone_no or doc.sender
        
        channel = doc.communication_medium
        
        if doc.content:
            print(f"--- DEBUG: Unlinked conversation content length: {len(doc.content)} ---")
            user_message, is_bot_message = extract_latest_message_from_content(doc.content)
            print(f"--- DEBUG: Extracted message from unlinked: '{user_message}' ---")
            print(f"--- DEBUG: Is bot message: {is_bot_message} ---")
            
            # CRITICAL: Skip if the latest message is from the bot (sent by "You")
            if is_bot_message:
                print(f"--- Sales Bot Hook Skipped: Latest message is from bot (sender: 'You') ---")
                return
        else:
            user_message = None
            print(f"--- DEBUG: No content in unlinked conversation ---")
    else:
        # Skip other types of communications
        print(f"--- Sales Bot Hook Skipped: Not a conversation document. Reference: {doc.reference_doctype} ---")
        return

    if not customer_identifier or not user_message:
        print(f"--- Sales Bot Hook Skipped: Missing identifier or content. Identifier: '{customer_identifier}', Message: '{user_message}' ---")
        frappe.log_error(
            "Sales Bot Hook Skipped",
            f"Missing identifier or content. Identifier: '{customer_identifier}', Message: '{user_message}'",
        )
        return

    # If all checks pass, ingest the message into the sales conversation engine
    print(f"--- Sales Bot Hook SUCCESS: Calling ingest_message for {customer_identifier} ---")
    frappe.log_error(
        "Sales Bot Hook SUCCESS: Calling ingest_message",
        f"From: {customer_identifier} | Channel: {channel} | Message: {user_message}",
    )
    
    ingest_message(
        channel=channel,
        customer_identifier=customer_identifier,
        user_message=user_message,
    ) 


def extract_latest_message_from_content(html_content):
    """
    Extract the latest message text from HTML-formatted conversation content.
    The content contains multiple message entries, we want the most recent one.
    Returns tuple: (message_text, is_bot_message)
    """
    try:
        from bs4 import BeautifulSoup
        import re
        
        print(f"--- DEBUG: Parsing HTML content of length {len(html_content)} ---")
        
        # Parse the HTML content
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all message entries (our formatted divs)
        message_entries = soup.find_all('div', class_='message-entry')
        print(f"--- DEBUG: Found {len(message_entries)} message entries ---")
        
        if message_entries:
            # Get the last (most recent) message entry
            latest_entry = message_entries[-1]
            print(f"--- DEBUG: Latest entry HTML: {str(latest_entry)[:200]}... ---")
            
            # Check if this is a bot message by looking for "You" as the sender
            sender_strong = latest_entry.find('strong')
            is_bot_message = False
            if sender_strong:
                sender_text = sender_strong.get_text().strip()
                is_bot_message = sender_text == "You"
                print(f"--- DEBUG: Sender text: '{sender_text}', Is bot: {is_bot_message} ---")
            
            # Extract text content, removing sender name and timestamp
            # The structure is: <strong>Sender</strong> <span>timestamp</span> arrow
            #                   <div>actual message content</div>
            content_div = latest_entry.find('div')
            if content_div:
                message_text = content_div.get_text().strip()
                print(f"--- DEBUG: Found content div with text: '{message_text}' ---")
                return message_text, is_bot_message
            else:
                # Fallback: get all text and try to extract message part
                full_text = latest_entry.get_text().strip()
                print(f"--- DEBUG: No content div, using full text: '{full_text}' ---")
                # Remove arrows and extra whitespace
                full_text = re.sub(r'[→←]', '', full_text).strip()
                # Try to get everything after timestamp (rough heuristic)
                lines = full_text.split('\n')
                if len(lines) > 1:
                    result = lines[-1].strip()
                    print(f"--- DEBUG: Using last line: '{result}' ---")
                    return result, is_bot_message
                print(f"--- DEBUG: Using full text: '{full_text}' ---")
                return full_text, is_bot_message
        else:
            # Fallback: if no structured message entries, get plain text
            plain_text = soup.get_text().strip()
            print(f"--- DEBUG: No message entries found, using plain text: '{plain_text}' ---")
            return plain_text, False
            
    except Exception as e:
        error_msg = f"Error extracting latest message from content: {str(e)}"
        print(f"--- DEBUG: {error_msg} ---")
        frappe.logger().error(error_msg)
        # Fallback: return the raw content stripped of HTML
        import re
        fallback = re.sub(r'<[^>]+>', '', html_content).strip() if html_content else None
        print(f"--- DEBUG: Using fallback text: '{fallback}' ---")
        return fallback, False 