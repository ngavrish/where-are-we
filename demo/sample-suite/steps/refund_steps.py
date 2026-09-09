from behave import given, when, then


@given("the invoice is settled")
def invoice_settled(context):
    context.invoice_state = "settled"


@when("they request a refund")
def request_refund(context):
    assert context.invoice_state == "settled"
    context.refund = "queued"


@then("the refund is queued")
def refund_queued(context):
    assert context.refund == "queued"


@given("the payment has been captured")
def payment_captured(context):
    context.payment = "captured"
