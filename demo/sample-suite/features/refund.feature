Feature: Refund
  Scenario: Refund a settled invoice
    Given the user is logged in
    And the invoice is settled
    When they request a refund
    Then the refund is queued
