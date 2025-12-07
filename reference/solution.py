#!/usr/bin/env python3
"""Payment agent with call recording and PCI-compliant payment collection.

Lab 2.7 Deliverable: Demonstrates call recording configuration,
consent flow, and secure payment collection using the SWML pay method.
Card data is collected via IVR and never passes through the LLM.
"""

import uuid
from signalwire_agents import AgentBase, AgentServer, SwaigFunctionResult
from fastapi import Request
from fastapi.responses import JSONResponse


# Test card numbers for different scenarios
TEST_CARDS = {
    "4111111111111111": "success",      # Visa - success
    "4000000000000002": "declined",     # Visa - declined
    "5555555555554444": "success",      # Mastercard - success
}


class PaymentAgent(AgentBase):
    """Payment processing agent with recording controls and PCI-compliant payments."""

    def __init__(self):
        super().__init__(name="payment-agent")

        # Recording configuration
        self.set_params({
            "record_call": True,
            "record_format": "mp3",
            "record_stereo": True  # Separate caller/agent channels
        })

        self.prompt_add_section(
            "Role",
            "You process payments for customers. "
            "Always disclose recording at call start."
        )

        self.prompt_add_section(
            "Recording Policy",
            bullets=[
                "Disclose recording at call start",
                "Use process_payment function for card collection",
                "Card data is collected securely via IVR",
                "Never ask customer to speak card numbers"
            ]
        )

        self.add_language("English", "en-US", "rime.spore")

        self._setup_functions()

    def _setup_functions(self):
        """Define payment and recording control functions."""

        @self.tool(
            description="Get recording consent from caller",
            parameters={
                "type": "object",
                "properties": {
                    "consent_given": {
                        "type": "string",
                        "enum": ["yes", "no"],
                        "description": "Whether caller consents to recording"
                    }
                },
                "required": ["consent_given"]
            }
        )
        def handle_consent(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            consent_given = args.get("consent_given", "")
            if consent_given == "yes":
                return (
                    SwaigFunctionResult(
                        "Thank you for your consent. How can I help you today?"
                    )
                    .update_global_data({"recording_consent": True})
                    .record_call(control_id="main", stereo=True, format="mp3")
                )
            else:
                return (
                    SwaigFunctionResult(
                        "No problem, this call will not be recorded. "
                        "How can I help you today?"
                    )
                    .update_global_data({"recording_consent": False})
                )

        @self.tool(
            description="Process payment for customer",
            parameters={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "string",
                        "description": "Amount to charge (e.g., '49.99')"
                    }
                },
                "required": ["amount"]
            }
        )
        def process_payment(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            amount = args.get("amount", "0.00")

            # Get public URL from SDK (auto-detected from ngrok/proxy headers)
            base_url = self.get_full_url().rstrip('/')
            payment_url = f"{base_url}/payment"

            # Card data collected via IVR - never touches the LLM
            return (
                SwaigFunctionResult(
                    "I'll collect your payment securely. "
                    "Please enter your card number using your phone keypad.",
                    post_process=True
                )
                .pay(
                    payment_connector_url=payment_url,
                    charge_amount=amount,
                    input_method="dtmf",
                    security_code=True,
                    postal_code=True,
                    max_attempts=3,
                    ai_response=(
                        "The payment result is ${pay_result}. "
                        "If successful, confirm the payment. "
                        "If failed, apologize and offer to try another card."
                    )
                )
            )


def create_server():
    """Create AgentServer with payment gateway endpoint."""
    server = AgentServer(host="0.0.0.0", port=3000)

    # Register the payment agent
    agent = PaymentAgent()
    server.register(agent, "/")

    # Add the mock payment gateway endpoint
    @server.app.post("/payment")
    async def payment_gateway(request: Request):
        """Mock payment gateway endpoint.

        In production, this would connect to a real payment processor
        like Stripe, Square, or Braintree.
        """
        data = await request.json()

        card_number = data.get("payment_card_number", "")
        charge_amount = data.get("charge_amount", "0.00")

        last_four = card_number[-4:] if len(card_number) >= 4 else "****"
        print(f"Payment: card=****{last_four}, amount=${charge_amount}")

        scenario = TEST_CARDS.get(card_number, "success")

        if scenario == "success":
            return JSONResponse({
                "charge_id": f"ch_{uuid.uuid4().hex[:12]}",
                "error_code": None,
                "error_message": None
            })
        else:
            return JSONResponse({
                "charge_id": None,
                "error_code": "card_declined",
                "error_message": "Your card was declined"
            })

    return server


if __name__ == "__main__":
    server = create_server()
    server.run()
