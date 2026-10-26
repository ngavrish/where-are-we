Feature: Login
  Scenario: A returning customer signs in
    Given the user is logged in
    When they open the billing page
    Then the account balance is shown
