Feature: API checkout
  Scenario: Checkout over the API
    Given a user has logged in
    When the cart is submitted
    Then the order is accepted
