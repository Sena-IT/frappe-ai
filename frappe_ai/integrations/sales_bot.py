import frappe
from frappe_ai.frappe_ai.doctype.sales_conversation.sales_conversation import ingest_message

def process_incoming_communication(doc, method):
    """
    This function is triggered by a hook on the WhatsApp Message DocType.
    It checks if the message is incoming and passes it to the Sales Bot.
    """
    print(f"--- Sales Bot Hook Triggered for WhatsApp Message: {doc.name}, Method: {method} ---")
    frappe.log_error(
        "Sales Bot Hook Triggered",
        f"Processing WhatsApp Message: {doc.name}, Method: {method}"
    )

    # We only care about incoming messages
    if doc.type != "Incoming":
        print(f"--- Sales Bot Hook Skipped: Not an 'Incoming' message. Type is '{doc.type}'. ---")
        frappe.log_error(
            "Sales Bot Hook Skipped",
            f"Not an 'Incoming' message. Type is '{doc.type}'."
        )
        return

    # Extract data from the WhatsApp Message document
    customer_identifier = doc.get("from")
    user_message = doc.get("message")

    if not customer_identifier or not user_message:
        print(f"--- Sales Bot Hook Skipped: Missing identifier or content. Identifier: '{customer_identifier}', Message: '{user_message}' ---")
        frappe.log_error(
            "Sales Bot Hook Skipped",
            f"Missing identifier or content. Identifier: '{customer_identifier}', Message: '{user_message}'",
        )
        return

    # The channel is implicitly WhatsApp
    channel = "WhatsApp"

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