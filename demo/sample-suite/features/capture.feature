Feature: Capture
  Scenario: Refund only after capture
    Given the payment has been captured
    Then a refund is allowed

  Scenario: API capture path
    Given the payment has been fully captured
    Then a refund is allowed
