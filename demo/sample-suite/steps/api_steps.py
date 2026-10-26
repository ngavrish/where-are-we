from behave import given, when, then

# NOTE: near-duplicate of auth_steps."the user is logged in" — the overlap
# where-are-we surfaces. Two phrases, two modules, same intent.
@given("a user has logged in")
def api_user_logged_in(context):
    context.token = "api-token"


@when("the cart is submitted")
def submit_cart(context):
    context.submitted = True


@then("the order is accepted")
def order_accepted(context):
    assert context.submitted


# near-duplicate of refund_steps."the payment has been captured" — one author
# wrote "fully". Jaccard 0.83, so where-are-we flags the pair.
@given("the payment has been fully captured")
def payment_fully_captured(context):
    context.payment = "captured"
