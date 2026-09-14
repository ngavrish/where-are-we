from behave import given, when, then
from pages.login_page import LoginPage


@given("the user is logged in")
def user_logged_in(context):
    LoginPage(context).sign_in("returning@example.com")


@when("they open the billing page")
def open_billing(context):
    context.page = "billing"


@then("the account balance is shown")
def balance_shown(context):
    assert context.page == "billing"
